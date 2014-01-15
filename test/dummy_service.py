import os
import sys
import time

sys.path.append("/Users/aditya/projects/utility/aws_dns")
from system_v import service

base_dir  = os.path.abspath(".")
pidfile   = os.path.join(base_dir, "dat/dummy.pid")
test_file = os.path.join(base_dir, "dat/dummy.dat")
log_file  = os.path.join(base_dir, "dat/dummy.log")

class dummy_service(service):
	def __init__(self):
		super(dummy_service, self).__init__("dummy_service", pidfile)
		self.terminating = False

	def run(self):
		try:
			self.fd = open(test_file, "w+")
		except Exception as e:
			self.log_failure(str(e))
			self.log_status(False)
			sys.exit(1)
		else:
			self.log_status(True)

		while True:
			self.fd.write("Poop\n")
			time.sleep(1)

	def terminate(self, signal, frame):
		if not self.terminating:
			self.terminating = True
			self.fd.write("Terminated\n")
			self.fd.close()
			sys.exit(0)

s = dummy_service()
r = {
	"start"        : s.start,
	"stop"         : s.stop,
	"restart"      : s.restart,
	"try-restart"  : s.try_restart,
	"reload"       : s.reload,
	"force-reload" : s.force_reload,
	"status"       : s.status
}.get(sys.argv[1], s.usage)()
sys.exit(r)
