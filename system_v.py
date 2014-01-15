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
  - Registration of the signal handler for `SIGTERM`.
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

  - Subclassing the `service` class.
  - Overriding `run` to implement the daemon.
  - Optionally overriding `terminate` to respond to `SIGTERM` (e.g. closing file
    descriptors).
  - Optionally overriding the `restart`, `reload`, and `force_reload` functions.
  - Optionally override `make_daemon`. You would want to do this if, for
    example, the daemon is created by another program. In this case, the
    `SIGTERM` handler and PID file management must be done by the external
    program.
  - Logging the initialization of the daemon in the `run` method.
    - The daemon must call `self.log_status(True)` or `self.log_status(False)`
      to report the initialization status.
    - The daemon can optionally call `self.log_warning` and `self.log_failure`
      to log error messages.
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
import subprocess
from colorama import Fore
from collections import namedtuple
from select import select

"""
Debian exit codes. These do not agree with the LSB status codes.
"""

exit_success   = 0
exit_no_action = 1
exit_failure   = 2

"""
Debian status codes. Happily, these agree with the LSB status codes.
"""

status_running              = 0
status_stopped_with_pidfile = 1
status_stopped_with_lock    = 2
status_stopped              = 3
status_unknown              = 4

"""
Action codes for the `service` class.
"""

assert_running = 0
assert_stopped = 1
assert_none    = 2

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

		# We need to flush the output stream after each logging
		# operation. Otherwise, forking the parent process will
		# duplicate the output buffer, causing two messages to be
		# printed.
		sys.stdout.flush()

	"""
	Used to log an action pertaining to a service, such as starting,
	stopping, or reloading the configuration. This function call should be
	followed by a call to `log_status`.
	"""
	def log_action(self, msg):
		print(" * {0}".format(msg), end="")
		sys.stdout.flush()
		self.fill = self.margin - 3 - len(msg)

	"""
	Used to log whether a service has started or stopped successfully.
	"""
	def log_status(self, s):
		if s:
			print("\033[{0}C[ OK ]".format(self.fill))
			sys.stdout.flush()
		elif not s:
			print("\033[{0}C[{1}fail{2}]".format(self.fill, Fore.RED, Fore.RESET))
			sys.stdout.flush()

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
		print(" * {0}: {1}".format(self.service, msg))
		sys.stdout.flush()

	"""
	Used to log a warning message.
	"""
	def log_warning(self, msg):
		print(" {0}*{1} {2}: {3}".format(Fore.YELLOW, Fore.RESET, self.service, msg))
		sys.stdout.flush()

	"""
	Used to log a failure message.
	"""
	def log_failure(self, msg):
		print(" {0}*{1} {2}: {3}".format(Fore.RED, Fore.RESET, self.service, msg))
		sys.stdout.flush()

class service:
	"""
	Summary of parameters:

          - `service_path` is the path to the service script.
	  - `pidfile` is the path to the PID file.
	  - `retry` is the number of times the daemon should be sent `SIGTERM`
	    before being sent `SIGKILL`.
	  - `sleep` is the number of seconds to sleep in between attempts to
	    terminate the daemon gracefully.
	"""
	def __init__(self, service_path, pidfile, retry = 5, sleep = 0.1):
		assert(retry >= 0)
		assert(sleep  >= 0)

		self.parent       = True
		self.service_path = service_path
		self.pidfile      = pidfile
		self.retry        = retry
		self.sleep        = sleep
		self.log          = logger(os.path.basename(service_path))

	"""
	Spawns the daemon. The parent process stays alive until it ensures that
	the daemon has successfully initialized and logs any error messages,
	since the daemon has its standard streams redirected to `/dev/null`. If
	the daemon was created successfully, the parent returns true; otherwise,
	it returns false.
	
	The derived class should override this method if the daemon should be
	created by other means; such a case is when the daemon is created by an
	external program.
	"""
	def make_daemon(self):
		# Used to communicate warning messages.
		(self.warning_get, self.warning_put) = os.pipe()
		# Used to communicate failure messages.
		(self.failure_get, self.failure_put) = os.pipe()
		# Used to communicate the initialization status.
		(self.status_get, self.status_put) = os.pipe()

		try:
			pid = os.fork()
			# Have the parent process monitor the status of the
			# daemon.
			if pid > 0:
				return self.monitor_daemon()
		except OSError as e:
			self.log.log_status(False)
			self.log.log_failure("First fork failed: {0}.".format(e))
			return False

		self.parent = False
		os.chdir("/")
		os.setsid()
		os.umask(0)

		try:
			pid = os.fork()
			# Terminate the parent process.
			if pid > 0:
				sys.exit(0)
		except OSError as e:
			self.log.log_status(False)
			self.log.log_failure("Second fork failed: {0}.".format(e))
			return False

		# Register the handlers.
		signal.signal(signal.SIGTERM, self.terminate)
		atexit.register(self.remove_pidfile)

		# Write the daemon's PID to `pidfile`.
		pid = str(os.getpid())
		try:
			with open(self.pidfile, "w+") as f:
				f.write(pid)
		except IOError as e:
			self.log.log_status(False)
			self.log.log_failure("Failed to write to PID file: {0}".format(e))
			return False

		# Flush remaining buffer contents.
		sys.stdout.flush()
		sys.stderr.flush()

		try:
			# Redirect standard streams to `/dev/null`.
			si = open(os.devnull, "r")
			so = open(os.devnull, "a+")
			se = open(os.devnull, "a+")
		except IOError as e:
			self.log.log_status(False)
			self.log.log_failure("Failed to open `/dev/null`: {0}".format(e))
			return False

		os.dup2(si.fileno(), sys.stdin.fileno())
		os.dup2(so.fileno(), sys.stdout.fileno())
		os.dup2(se.fileno(), sys.stderr.fileno())
		return True
	
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
			r, w, x = select(rlist, wlist, xlist)
			if len(x) != 0:
				self.log.log_status(False)
				self.log.log_failure("Error reading from pipe.")
				self.close_pipes()
				return False
			elif self.status_get in r:
				# We must log the status before the failure
				# messages, because the `[ OK ]` or `[fail]`
				# status needs to occur on the same line as the
				# starting daemon message.
				status = int(os.read(self.status_get, 1).decode("utf-8"))
				self.log.log_status(status == exit_success)

				# Now we log any messages sent using the
				# message pipes.
				if self.failure_get in r:
					data = os.read(self.failure_get, 512).decode("utf-8")
					# Skip the last element of the
					# splitting, because it must be empty.
					for msg in data.split("\n")[:-1]:
						self.log.log_failure(msg)
				if self.warning_get in r:
					data = os.read(self.warning_get, 512).decode("utf-8")
					for msg in data.split("\n")[:-1]:
						self.log.log_warning(msg)

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
	PID file is removed, and -1 is returned. The `assertion` parameter,
	which is one of `assert_running`, `assert_stopped`, or `assert_none`,
	determines whether this function will log a status.
	"""
	def get_pid(self, assertion):
		Status = namedtuple("Status", ["pid", "status"])

		if os.path.isfile(self.pidfile):
			try:
				with open(self.pidfile) as f:
					pid = int(f.read().strip())
			except IOError as e:
				if assertion == assert_running:
					self.log.log_status(False)
				self.log.log_warning("Failed to read PID file: {0}".format(e))
				return Status(-1, status_unknown)
			except ValueError as e:
				if assertion == assert_running:
					self.log.log_status(False)
				self.log.log_warning("Invalid PID in PID file: {0}".format(e))
				self.remove_pidfile()
				return Status(-1, status_stopped_with_pidfile)
		else:
			if assertion == assert_running:
				self.log.log_status(False)
			return Status(-1, status_stopped)

		try:
			os.kill(pid, 0)
		except OSError:
			if assertion == assert_running:
				self.log.log_status(False)
			self.remove_pidfile()
			return Status(-1, status_stopped)
		else:
			if assertion == assert_stopped:
				self.log.log_status(False)
			return Status(pid, status_running)

	"""
	Removes the PID file.
	"""
	def remove_pidfile(self):
		if os.path.isfile(self.pidfile):
			try:
				os.remove(self.pidfile)
			except OSError as e:
				self.log.log_warning("Failed to remove PID file: {0}".format(e))

	"""
	Called when `SIGTERM` is sent to the daemon. The derived class will
	likely need to override this method.
	"""
	def terminate(self, signal, frame):
		pass

	"""
	Used by the daemon to log warnings during initialization.
	"""
	def log_warning(self, msg):
		if self.parent:
			return
		os.write(self.warning_put, bytes(msg + "\n", "utf-8"))

	"""
	Used by the daemon to log failures during initialization.
	"""
	def log_failure(self, msg):
		if self.parent:
			return
		os.write(self.failure_put, bytes(msg + "\n", "utf-8"))

	"""
	Used by the daemon to log the initialization status.
	"""
	def log_status(self, success):
		if self.parent:
			return
		if success:	
			os.write(self.status_put, bytes("0", "utf-8"))
		else:
			os.write(self.status_put, bytes("1", "utf-8"))

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
		self.log.log_action("Starting AWS DNS service.")

		# Check if the service is already running.
		(_, status) = self.get_pid(assert_stopped)
		if status == status_running:
			return exit_no_action

		success = self.make_daemon()
		if self.parent:
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
		self.log.log_action("Stopping AWS DNS service.")

		(pid, status) = self.get_pid(assert_running)
		if not (status == status_running or status == status_unknown):
			return exit_no_action

		# Attempt to terminate the process.
		killed = False
		try:
			for _ in range(self.retry):
				os.kill(pid, signal.SIGTERM)
				time.sleep(self.sleep)
			killed = True
			os.kill(pid, signal.SIGKILL)
		except OSError as e:
			if "No such process" not in str(e.args):
				self.log.log_status(False)
				self.log.log_failure("Unable to stop service: {0}".format(e))
				self.remove_pidfile()
				return exit_failure

		self.log.log_status(True)
		if killed:
			self.log.log_warning("Service terminated via SIGKILL.")
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
		(_, status) = self.get_pid(assert_none)
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
		_, status = self.get_pid(assert_none)
		return status

	"""
	Prints usage information.
	"""
	def usage(self):
		print(" * Usage: {0} {{start|stop|reload|force-reload|restart|try-restart|status}}.".
			format(self.service_path))
