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

I have adapted the original daemonizing code in the following ways:

  - Only one fork is used instead of two; it is assumed that the daemon will not
    attempt to do something stupid like read from a TTY.
  - The standard streams are closed instead of redirected to `/dev/null`.
    Daemons should not be using the standard streams anyway, so this seemed like
    the cleanest option.
  - Standard output and error are flushed by the parent process before `fork` is
    called. Otherwise, this might lead to duplicate messages being printed
    later.

# Usage

If you are not familiar with system initialization or init scripts, you may wish
to consult the [notes][unix_notes] that I have written on these topics. In
addition, you may wish to familiarize yourself with the init script conventions
of your target Linux distribution.

The class derived from `service` must fulfill the following responsibilities:

  - Subclassing the `service` class.
  - Overriding `run` to implement the daemon.
  - Overriding `terminate` to respond to `SIGTERM` (e.g. closing file
    descriptors).
  - Error logging.
  - Optionally overriding the `restart`, `reload`, and `force_reload` functions.
  - Optionally override `make_daemon`. You would want to do this if, for
    example, the daemon is created by another program. In this case, the
    `SIGTERM` handler and PID file management must be done by the external
    program.
  - The daemon must call `self.log_status(True)` or `self.log_status(False)`
    to report the initialization status when `run` is called.
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
Assertion codes for the `service` class.
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
	  - `start_timeout` is the maximum number of floating-point seconds to
	    wait for the daemon to report a status after it enters `run`.
	  - `stop_timeout` is the maximum number of floating-point seconds to
	    wait for the daemon to respond to `SIGTERM`.
	"""
	def __init__(self, service_path, pidfile,  start_timeout = 10, stop_timeout = 1):
		self.service_name = os.path.basename(service_path)
		assert(start_timeout >= 0)
		assert(stop_timeout >= 0)
		assert(len(self.service_name) != 0)

		self.parent        = True
		self.service_path  = service_path
		self.pidfile       = pidfile
		self.start_timeout = start_timeout
		self.stop_timeout  = stop_timeout
		self.log           = logger(self.service_name)

	"""
	Spawns the daemon. The parent process stays alive until it ensures that
	the daemon has successfully initialized and logs any error messages,
	since the daemon has its standard streams redirected to `/dev/null`. If
	the daemon was created successfully, the parent returns true; otherwise,
	it returns false.
	
	The derived class should override this method if the daemon should be
	created by other means. Such a case is when the daemon is created by an
	external program.
	"""
	def make_daemon(self):
		# Flush remaining buffer contents initially, so that we do not
		# get duplicate messages printed later.
		sys.stdout.flush()
		sys.stderr.flush()

		# Used to communicate the initialization status.
		(self.status_get, self.status_put) = os.pipe()

		try:
			pid = os.fork()
		except OSError as e:
			self.log.log_status(False)
			self.log.log_failure("Fork failed: {0}.".format(e))
			return False

		# The parent monitors the initialization of the daemon.
		if pid > 0:
			return self.monitor_daemon(self.start_timeout)

		# The rest of this function should be entered by the daemon
		# only.
		self.parent = False

		try:
			# Disable any file permission restrictions.
			os.umask(0)
			# Make the daemon a new session leader to detach it from
			# the current terminal. This also makes the daemon the
			# leader of a new process group.
			os.setsid()
			# Change the directory to a predetermined existing
			# directory.
			os.chdir("/")
		except Exception as e:
			self.log.log_status(False)
			self.log.log_failure(str(e))
			sys.exit(1)

		# Register the handlers.
		signal.signal(signal.SIGTERM, self.terminate)
		atexit.register(self.remove_pidfile)

		# Write the daemon's PID to `pidfile`.
		pid = str(os.getpid())
		try:
			with open(self.pidfile, "w+") as f:
				f.write(pid)
		except Exception as e:
			self.log.log_status(False)
			self.log.log_failure("Failed to write to PID file: {0}".format(e))
			sys.exit(1)

		# Another option would be to redirect the standard streams to
		# `/dev/null`, but daemons should not really be using these
		# streams in the first place.
		os.close(sys.stdin.fileno())
		os.close(sys.stdout.fileno())
		os.close(sys.stderr.fileno())
		self.run()
	
	"""
	When the parent process forks to create a daemon, it must wait until it
	receives a status code from the daemon, so that it knows that
	initialization has proceeded successfully.
	"""
	def monitor_daemon(self, timeout):
		rlist = [self.status_get]
		wlist = []
		xlist = [self.status_get]
		while True:
			r, w, x = select(rlist, wlist, xlist, timeout)
			if len(x) == 1:
				self.log.log_status(False)
				self.log.log_failure("Error reading from pipe.")
				os.close(self.status_get)
				os.close(self.status_put)
				return False
			elif len(r) == 1:
				status = os.read(self.status_get, 1)[0]
				self.log.log_status(status == exit_success)
				os.close(self.status_get)
				os.close(self.status_put)
				return True
			else:
				self.log.log_status(False)
				self.log.log_failure("Exceeded timeout value.")
				os.close(self.status_get)
				os.close(self.status_put)
				return False

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
		self.log.close()

	"""
	Used by the daemon to log the initialization status.
	"""
	def log_status(self, success):
		if self.parent:
			return
		if success:	
			os.write(self.status_put, bytearray([0]))
		else:
			os.write(self.status_put, bytearray([1]))

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
		self.log.log_action("Starting {0}".format(self.service_name))

		# Check if the service is already running.
		(_, status) = self.get_pid(assert_stopped)
		if status == status_running:
			return exit_no_action

		# Create the daemon.
		return exit_success if self.make_daemon() else exit_failure

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
		self.log.log_action("Stopping {0}".format(self.service_name))

		(pid, status) = self.get_pid(assert_running)
		if not (status == status_running or status == status_unknown):
			return exit_no_action

		# Attempt to terminate the process.
		killed = False
		try:
			# TODO: Use `sigqueue` with semaphore and
			# `self.stop_timeout`.
			for _ in range(5):
				os.kill(pid, signal.SIGTERM)
				time.sleep(0.1)
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
	Reloads the configuration, possibly without restarting the service. By
	default, this calls `force_reload`. The derived class can override this
	function if a more efficient implementation is possible.
	"""
	def reload(self):
		return self.reload()

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
