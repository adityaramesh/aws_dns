"""
File Name: system_v.py
Author:    Aditya Ramesh
Date:      01/13/2014
Contact:   _@adityaramesh.com

# Introduction

This file contains a service class that makes writing System V init scripts
easier. It is based on the `daemon3x.py` file written by Chris Hager, and has
been adapted to include the following additional features:

  - Creation and management of the PID file.
  - Implementation of the required init script functions (consult the
    documentation for the inidividual member functions for more details).
  - Logging useful messages during the course of execution of the init script
    functions.
  - Formatting the log messages according to the conventions of the target
    platform.

# Usage

If you are not familiar with system initialization or init scripts, you may wish
to consult the [notes][unix_notes] that I have written on these topics. In
addition, you may wish to familiarize yourself with the init script conventions
of your target Linux distribution.

The class derived from `service` must fulfill the following responsibilities:

  - Subclassing the `service` class and overriding `run`.
  - Optionally overriding the `restart`, `reload`, and `force_reload` functions.
  - Logging the initialization of the daemon in the `run` method, and calling
    `self.log.log_status(True)` or `self.log.log_status(False)` appropriately.
  - Parsing the configuration file (if any).

[unix_notes]:
https://github.com/adityaramesh/notes/tree/master/unix
"Unix Notes"
"""

import os
import sys
import time
import atexit
import signal
import colorama
import subprocess
from collections import namedtuple

"""
Debian exit codes. These do not agree with the LSB status codes.
"""

exit_success   = 0
exit_no_action = 1
exit_failure   = 2

"""
Debian status codes. Happily, these agree with the LSB status codes.
"""

status_running           = 0
status_dead_with_pidfile = 1
status_dead_with_lock    = 2
status_dead              = 3
status_unknown           = 4

class logger:
	"""
	`service` is the name of the service that is being logged.
	"""
	def __init__(self, service):
		self.service = service
		out = subprocess.Popen(
			["tput", "cols"], stdout=subprocess.PIPE
		).communicate()[0]
		self.cols = int(out.decode("utf-8"))

		# Used to store the number of columns to advance before printing
		# the `[ OK ]` or `[fail]` status.
		self.fill = 0

		if self.cols >= 6:
			self.margin = self.cols - 7
		else:
			self.cols = 80
			self.margin = 73

	"""
	Used to log an action pertaining to a service, such as starting,
	stopping, or reloading the configuration. This function call should be
	followed by a call to `log_status`.
	"""
	def log_action(self, msg):
		print(" * {0}".format(msg), end="")
		self.fill = self.margin - 3 - len(msg)

	"""
	Used to log whether a service has started or stopped successfully.
	"""
	def log_status(self, s):
		if s:
			print("\033[{0}C[ OK ]".format(self.fill))
		elif not s:
			print("\033[{0}C[{1}fail{2}]".format(self.fill, Fore.RED, Fore.RESET))

	"""
	Used to log progress pertaining to a service.
	"""
	def log_progress(self, msg):
		# Does nothing on the distributions that I checked.
		pass

	"""
	Used to log a success message.
	"""
	def log_success(self, msg):
		print("{0}: * {1}".format(service, msg))

	"""
	Used to log a warning message.
	"""
	def log_warning(self, msg):
		print("{0}: {1}*{2} {3}".format(service, Fore.YELLOW, Fore.RESET, msg))

	"""
	Used to log a failure message.
	"""
	def log_failure(self, msg):
		print("{0}: {1}*{2} {3}".format(service, Fore.RED, Fore.RESET, msg))

class service:
	"""
	Summary of parameters:

	  - `pidfile` is the path to the PID file.
	  - `retry` is the number of times the daemon should be sent `SIGTERM`
	    before being sent `SIGKILL`.
	  - `sleep` is the number of seconds to sleep in between attempts to
	    terminate the daemon gracefully.
	"""
	def __init__(self, pidfile, retry = 5, sleep = 0.1):
		assert(retry >= 0)
		assert(sleep  >= 0)

		self.pidfile = pidfile
		self.retry  = retry
		self.sleep   = sleep
		self.log     = logger("AWS DNS")

	"""
	Spawns the daemon. The parent process stays alive until it ensures that
	the daemon has successfully initialized and logs any error messages,
	since the daemon has its standard streams redirected to `/dev/null`.
	"""
	def daemonize(self):
		# Used to communicate warning messages.
		self.warning_get, self.warning_put = os.pipe()
		# Used to communicate failure messages.
		self.failure_get, self.failure_put = os.pipe()
		# Used to communicate the initialization status.
		self.status_get, self.status_put = os.pipe()

		# We need to be able to differentiate between the parent and
		# child process when this function returns.
		Status = namedtuple("Status", ["is_parent", "success"])

		try:
			pid = os.fork()
			# Have the parent process monitor the status of the
			# daemon.
			if pid > 0:
				return Status(True, self.monitor_daemon())
		except OSError as e:
			log.log_status(False)
			log.log_failure("First fork failed: {0}.".format(e))
			return Status(True, False)

		os.chdir("/")
		os.setsid()
		os.umask(0)

		try:
			pid = os.fork()
			# Terminate the parent process.
			if pid > 0:
				sys.exit(0)
		except OSError as e:
			log.log_status(False)
			log.log_failure("Second fork failed: {0}.".format(e))
			return Status(False, False)

		# Write the daemon's PID to `pidfile`.
		atexit.register(self.remove_pidfile)
		pid = str(os.getpid)
		try:
			with open(self.pidfile, "w+") as f:
				f.write(pid)
		except IOError as e:
			log.log_status(False)
			log.log_failure("Failed to write to PID file: {0}".format(e))
			return Status(False, False)

		# Flush remaining buffer contents.
		sys.stdout.flush()
		sys.stderr.flush()

		try:
			# Redirect standard streams to `/dev/null`.
			si = open(os.devnull, "r")
			so = open(os.devnull, "a+")
			se = open(os.devnull, "a+")
		except IOError as e:
			log.log_status(False)
			log.log_failure("Failed to open `/dev/null`: {0}".format(e))
			return Status(False, False)

		os.dup2(si.fileno(), sys.stdin.fileno())
		os.dup2(so.fileno(), sys.stdout.fileno())
		os.dup2(se.fileno(), sys.stderr.fileno())
		return Status(False, True)
	
	"""
	When the parent process forks to create a daemon, it must wait until it
	receives a status code from the daemon so that it can log any error
	messages.
	"""
	def monitor_daemon(self):
		rlist = [self.warning_get, self.failure_get, self.status_get]
		wlist = []
		xlist = [self.warning_get, self.failure_get, self.status_get]
		while True:
			r, w, x = select.select(rlist, wlist, xlist)
			if len(x) != 0:
				log.log_status(False)
				log.log_failure("Error reading from pipe.")
				self.close_pipes()
				return False
			elif status_get in rlist:
				# We must log the status before the failure
				# messages, because the `[ OK ]` or `[fail]`
				# status needs to occur on the same line as the
				# starting daemon message.
				status = int(os.read(status_get, 1).decode("utf-8"))
				log.log_status(status == exit_success)

				# Now we log any messages sent using the
				# message pipes.
				if failure_get in rlist:
					for msg in os.read(failure_get, 512).decode("utf-8").split("\n"):
						log.log_failure(msg)
				if warning_get in rlist:
					for msg in os.read(warning_get, 512).decode("utf-8").split("\n"):
						log.log_warning(msg)

				self.close_pipes()
				return True
			else:
				time.sleep(0.01)

	"""
	Closes the pipes used to communicate with the daemon.
	"""
	def close_pipes(self):
		os.close(self.warning_get)
		os.close(self.warning_put)
		os.close(self.failure_get)
		os.close(self.failure_put)
		os.close(self.status_get)
		os.close(self.status_put)

	"""
	Attempts to retrieve a PID from the PID file. If the PID in the PID file
	corresponds to an existing process, the PID is returned. Otherwise, the
	PID file is removed, and -1 is returned.
	"""
	def get_pid(self):
		Status = namedtuple("Status", ["pid", "status"])

		if os.path.isfile(self.pidfile):
			try:
				with open(self.pidfile) as f:
					pid = int(f.read().strip())
			except IOError as e:
				log.log_warning("Failed to read PID file: {0}".format(e))
				return Status(-1, status_unknown)
			except ValueError as e:
				log.log_warning("Invalid PID in PID file: {0}".format(e))
				return Status(-1, status_dead_with_pidfile)
		else:
			return Status(-1, status_dead)

		try:
			os.kill(pid, 0)
		except OSError:
			try:
				os.remove(self.pidfile)
			except OSError as e:
				log.log_failure("Failed to remove old PID file.")
				return Status(-1, status_dead_with_pidfile)
			return Status(-1, status_dead)
		else:
			return Status(pid, status_running)

	"""
	Removes the PID file.
	"""
	def remove_pidfile(self):
		if os.path.isfile(self.pidfile):
			try:
				os.remove(self.pidfile)
			except OSError as e:
				log.log_warning("Failed to remove PID file: {0}".format(e))

	"""
	Starts the daemon. Only the parent returns from this function; the
	return value is determined as follows:

	  - `exit_success` if the service was not running and was successfully
	    started.
	  - `exit_no_action` if the service was already running.
	  - `exit_failure` if the service could not be started.

	The child process (the daemon) terminates with exit code 1 if
	initialization was not successful. Otherwise, it enters the `run`
	function and continues to log the initialization process.
	"""
	def start(self):
		log.log_action("Starting AWS DNS service.")

		# Check if the service is already running.
		(_, status) = self.get_pid()
		if not (status == status_dead or status == status_dead_with_pidfile):
			log.log_status(False)
			return exit_no_action

		(is_parent, success) = self.daemonize()
		if is_parent:
			# Only the parent process should return from this
			# function.
			return exit_success if success else exit_failure
		elif not success:
			# The daemon was not initialized successfully, so we
			# terminate the child process.
			sys.exit(1)
		else:
			# The daemon should not return from `run`, but should
			# log whether initialization was successful, along with
			# the appropriate status.
			self.run()

	"""
	Stops the daemon. The return value of this function is determined as
	follows:

	  - `exit_success` is returned only if the PID file exists, was
	    successfully read, contained a PID referring to a valid process, and
	    the process was successfully terminated.
	  - `exit_failure` is returned only if the PID file exists, was
	    successfully read, contained a PID referring to a valid process, but
	    the process was not successfully terminated.
	  - `exit_no_action` is returned in all other cases.

	If the daemon was forcibly terminated via `SIGKILL`, `exit_success` is
	still returned, but a warning message is printed.
	"""
	def stop(self):
		log.log_action("Stopping AWS DNS service.")

		(pid, status) = self.get_pid()
		if status != status_running:
			log.log_status(False)
			return exit_no_action

		# Attempt to terminate the process.
		killed = False
		try:
			if self.retry > 0:
				os.kill(pid, signal.SIGTERM)
				for _ in range(self.retry - 1):
					time.sleep(self.sleep)
					os.kill(pid, signal.SIGTERM)
			killed = True
			os.kill(pid, signal.SIGKILL)
		except OSError as e:
			log.log_status(False)
			log.log_failure("Unable to stop service: {0}".format(e))
			self.remove_pidfile()
			return exit_failure

		log.log_status(True)
		if killed:
			log.log_warning("Service terminated via SIGKILL.")
		self.remove_pidfile()
		return exit_success

	"""
	Restarts the service. The derived class can override this function if a
	more efficient implementation is possible.
	"""
	def restart(self):
		s = self.stop()
		if s == exit_success or s == exit_no_action:
			return self.start()
		else:
			return exit_failure

	"""
	Restarts the service if it is already running.
	"""
	def try_restart(self):
		(_, status) = self.get_pid()
		if status != status_running:
			return exit_no_action
		else:
			return self.restart()
	
	"""
	This method should be overridden by the derived class if the
	functionality is desired, as reloading the configuration file is
	dependent on the daemon. By default, it does nothing.
	"""
	def reload(self):
		pass

	"""
	By default, this restarts the daemon. The derived class can override
	this function if a more efficient implementation is possible.
	"""
	def force_reload(self):
		return self.restart()

	"""
	Returns the status associated with the service.
	"""
	def status(self):
		_, status = self.get_pid()
		return status
