#! /opt/local/bin/python

import json
import logging
import os
import subprocess
import time
import urllib3
from daemon3x import daemon
from subprocess import Popen

def get_set_ip(domain, zone_id):
	out, err = Popen(
		['aws', 'route53', 'list-resource-record-sets', '--hosted-zone-id', zone_id], 
		stdout=subprocess.PIPE, stderr=subprocess.PIPE
	).communicate()
	sets = json.loads(out.decode("utf-8"))["ResourceRecordSets"]
	l = list(filter(lambda r : r["Type"] == "A" and r["Name"] == domain, sets))
	if len(l) == 0:
		return None
	else:
		if len(l) > 1:
			logging.warning("Multiple A records match domain: using first match.")
		addresses = list(filter(lambda r : "Value" in r, l[0]["ResourceRecords"]))
		if len(addresses) == 0:
			logging.critical("Matching A record has no address value.")
		elif len(addresses) > 1:
			logging.warning("Matching A record has multiple address values.")
			logging.warning("Only the first one will be considered.")
		return addresses[0]["Value"]

def get_public_ip():
	http = urllib3.PoolManager()
	r = http.request("GET", "http://ip.42.pl/raw")
	if r.status != 200:
		raise Exception("Failed to get public IP.")
	try:
		return r.data.decode("utf-8")
	except UnicodeError:
		raise Exception("Failed to decode response.")

def update_record(domain, zone_id, old_ip, new_ip):
	change_query = json.dumps({
		"Changes": [
			{
				"Action": "DELETE",
				"ResourceRecordSet": {
					"Name": domain,
					"Type": "A",
					"ResourceRecords": [{"Value": old_ip}],
					"TTL": 300
				}
			},
			{
				"Action": "CREATE",
				"ResourceRecordSet": {
					"Name": domain,
					"Type": "A",
					"ResourceRecords": [{"Value": new_ip}],
					"TTL": 300
				}
			}
		]
	})
	out, err = Popen(
		['aws', 'route53', 'change-resource-record-sets',
		'--hosted-zone-id', zone_id, '--change-batch', change_query],
		stdout=subprocess.PIPE, stderr=subprocess.PIPE
	).communicate()
	info = json.loads(out.decode("utf-8"))
	return (info["ChangeInfo"]["Status"] == "INSYNC", info["ChangeInfo"]["Id"])

def is_change_committed(change_id):
	out, err = Popen(
		['aws', 'route53', 'get-change', '--id', change_id],
		stdout=subprocess.PIPE, stderr=subprocess.PIPE
	).communicate()
	info = json.loads(out.decode("utf-8"))
	return info["ChangeInfo"]["Status"] == "PENDING" 

def initialize(domain, zone_id):
	try:
		set_ip = get_set_ip(domain, zone_id)
	except Exception as e:
		logging.warning("Failed to look up A record: " + str(e))
		return
	try:
		cur_ip = get_public_ip()
	except Exception as e:
		logging.critical("Failed getting public IP: " + str(e))
		return
	logging.info("Current address associated with domain: " + set_ip)
	logging.info("Current public IP address: " + cur_ip)

	if set_ip != cur_ip:
		try:
			change_id = update_record(domain, zone_id, set_ip, cur_ip)
			change_pending = True
			logging.info("Successfully updated record.")
		except Exception as e:
			logging.warning("Failed to update record: " + str(e))
			return
	else:
		change_id = ""
		change_pending = False
	return (set_ip, cur_ip, change_pending, change_id)

def main():
	logging.basicConfig(filename="/var/log/aws_ip_sync.log", filemode="w", level=logging.DEBUG)
	try:
		config = json.load(open("/etc/default/aws_ip_sync.json"))
	except IOError as e:
		logging.critical(str(e))
		return
	except Exception as e:
		logging.critical("Error parsing configuration file: " + str(e))
		return

	try:
		domain = config["domain-name"]
		zone_id = config["hosted-zone-id"]
	except KeyError as e:
		logging.critical("Missing configuration parameter.")

	if not domain.endswith("."):
		logging.critical("Value for \"domain-name\" does not end with \".\"")
		return

	while True:
		status = initialize(domain, zone_id)
		if status is not None:
			break
		else:
			logging.warning("Initialization failed.")
			logging.warning("Next attempt in 10 seconds.")
			time.sleep(10)

	set_ip = status[0]
	cur_ip = status[1]
	change_pending = status[2]
	change_id = status[3]
	logging.info("Initialization successful.")

	while True:
		time.sleep(300)
		if change_pending:
			try:
				if not change_committed(change_id):
					logging.info("Previous change not yet committed.")
					logging.info("Next check in 5 minutes.")
					continue
				else:
					change_pending = False
					set_ip = cur_ip
			except Exception as e:
				logging.warning("Failed to get change status: " + e);
				logging.warning("Next attempt in 5 minutes.")
				continue
		try:
			cur_ip = get_public_ip()
		except Exception as e:
			logging.warning("Failed to get public IP: " + e);
			logging.warning("Next attempt in 5 minutes.")
		if set_ip != cur_ip:
			try:
				change_id = update_record(domain, zone_id, set_ip, cur_ip)
				change_pending = True
				logging.info("Successfully updated record.")
				logging.info("Next check in 5 minutes.")
			except Exception as e:
				logging.warning("Failed to update record: " + str(e))
				logging.warning("Next attempt in 5 minutes.")
				continue
		else:
			logging.info("Public IP has not changed.")
			logging.info("Next check in 5 minutes.")

class my_daemon(daemon):
	def run(self):
		main()

d = my_daemon("/var/run/aws_ip_sync.pid")
d.start()
