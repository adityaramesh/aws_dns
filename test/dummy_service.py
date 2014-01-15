import os
import sys
import time

sys.path.append("/Users/aditya/projects/utility/aws_dns")
from system_v import service

class dummy_service(service):
	def __init__(self):
		super(dummy_service, self).__init__("/Users/aditya/projects/utility/aws_dns/dat/dummy.pid")

	def run(self):
		try:
			f = open("/Users/aditya/projects/utility/aws_dns/dat/test.txt", "w+")
			f.write("Poop\n")
			f.close()
			self.log_status(True)
		except Exception as e:
			self.log_failure(str(e))
			self.log_status(False)

s = dummy_service()

{
 	"start"        : s.start,
 	"stop"         : s.stop,
	"restart"      : s.restart,
	"try-restart"  : s.try_restart,
	"reload"       : s.reload,
	"force-reload" : s.force_reload,
	"status"       : s.status
}[sys.argv[1]]()
