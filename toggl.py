#!/usr/bin/env python
"""
toggl.py

Created by Robert Adams on 2012-04-19.
Last modified: Thu May 24, 2012 08:37PM

Modified by Morgan Howe (mthowe@gmail.com)
Last modified: Mon Apr 1, 2013

Copyright (c) 2012 D. Robert Adams. All rights reserved.
Copyright (c) 2013 Morgan Howe. All rights reserved.
"""

#############################################################################
### Configuration Section                                                 ###
###

# Do you want to ignore starting times by default?
IGNORE_START_TIMES = False

# Command to visit toggl.com
WWW_ADDRESS = "open http://www.toggl.com"

###                                                                       ###
### End of Configuration Section                                          ###
#############################################################################

from libtoggl import *

import datetime
import json
import os
import pytz
import sys
import time
import urllib
import argparse
import re
import dateutil.parser as date_parser

try:
    import configparser
except:
    import ConfigParser as configparser

TOGGL_URL = "https://www.toggl.com/api"
DEFAULT_DATEFMT = '%Y-%m-%d (%A)'
DEFAULT_ENTRY_DATEFMT = '%Y-%m-%d %H:%M%p'
DEFAULT_CACHE_PATH = '~/.toggl'
alias_dict = {}

class TogglCache:
    def __init__(self, cache_path, cache_enabled, max_age_days=0):
        self._cache_path = os.path.expanduser(cache_path)
        self._enabled = cache_enabled
        self._max_age_days = max_age_days

        if not os.path.exists(self._cache_path):
            os.makedirs(self._cache_path)

    @property
    def enabled(self):
        return self._enabled

    def cache_age_expired(self, cachemodtime):
        return (time.time() - cachemodtime) / (60 * 60 * 24) > self._max_age_days

    def read_cache_file(self, path):
        try:
            if self._max_age_days > 0 and self.cache_age_expired(os.path.getmtime(path)):
                print("Cache is expired.")
                return None
            f = open(path, "r")
            data = f.read()
            f.close()
            if data == "":
                data = None 
        except IOError:
            data = None

        return data

    def write_cache_file(self, path, data):
        try:
            f = open(path, "w")
            f.write(data)
            f.close()
        except IOError:
            print("Failed to update %s" % path)
            pass

    def read_project_cache(self):
        return self.read_cache_file("%s/%s" % (self._cache_path, "projects.cache"))

    def update_project_cache(self, data):
        return self.write_cache_file("%s/%s" % (self._cache_path, "projects.cache"), data)

    def read_workspace_cache(self):
        return self.read_cache_file("%s/%s" % (self._cache_path, "workspaces.cache"))

    def update_workspace_cache(self, data):
        return self.write_cache_file("%s/%s" % (self._cache_path, "workspaces.cache"), data)

    def read_client_cache(self):
        return self.read_cache_file("%s/%s" % (self._cache_path, "clients.cache"))

    def update_client_cache(self, data):
        return self.write_cache_file("%s/%s" % (self._cache_path, "clients.cache"), data)

def check_feature_support(proj):
    wsp = find_workspace(str(proj.workspace.id)) if proj.workspace else None
    if not wsp:
        print("Could not find workspace!")
        return False

    if wsp.profile_name == "Free":
        return False
    elif wsp.profile_name == "Pro":
        return True
    else:
        print("Unexpected profile name: %s" % wsp.profile_name)
        return False

def json_format(text):
    return json.dumps(text, sort_keys=False, indent=4, separators=(',', ':'))

def format_time_entry(entry, show_proj=True, verbose=False):
    """Utility function to print a time entry object and returns the
       integer duration for this entry."""

    # If the duration is negative, the entry is currently running so we
    # have to calculate the duration by adding the current time.
    is_running = ''

    e_time_str = " %s" % elapsed_time(int(get_entry_duration(entry)), separator='')
 
    # Get the project name (if one exists).
    tz = pytz.timezone(toggl_cfg.get('options', 'timezone'))
    project_name = ''
    if entry.project == None:
        project_name = " (No Project)"
    elif show_proj:
        project_name = " @%s" % entry.project.name
    else:
        start_time = date_parser.parse(entry.start_time).astimezone(tz)
        project_name = " %s" % start_time.date()

    if verbose:
        date_fmt = DEFAULT_ENTRY_DATEFMT
        if toggl_cfg.has_option('options', 'entry_datefmt'):
            date_fmt = toggl_cfg.get('options', 'entry_datefmt')

        st = date_parser.parse(entry.start_time).astimezone(tz).strftime(date_fmt)
        if entry.stop_time == None:
            et = ""
        else:
            et = date_parser.parse(entry.stop_time).astimezone(tz).strftime(date_fmt)

        return "[%s] %s%s%s%s (%s - %s)" % (entry.id, is_running, entry.desc, \
                project_name, e_time_str, st, et)
    else:
        return "%s%s%s%s" % (is_running, entry.desc, project_name, e_time_str)

def format_project_entry(proj, verbose=False):
    proj_id = ""
    if args.verbose_list:
        proj_id = "[%s] " % (proj.id)

    alias = find_alias_key_by_val(proj.name)
    alias_str = ""
    if alias is not None:
        alias_str = "(%s)" % alias

    return "%s %s%-10s %s [Workspace: (%s)]" % ('*' if proj.is_active else '-',
        proj_id, alias_str, proj.name, proj.workspace.name if proj.workspace else 'None')

def show_project(proj):
    print("%-30s: %d" % ("Project ID", proj.id))
    print("%-30s: %s" % ("Name", proj.name))
    print("%-30s: %s" % ("Workspace", proj.workspace.name if proj.workspace else "None"))
    print("%-30s: %s" % ("Client", proj.client.name if proj.client else "None"))
    print("%-30s: %s" % ("Billable", proj.billable))
    print("%-30s: %s" % ("Est. Work Hours", proj.estimated_workhours))
    print("%-30s: %s" % ("Auto-calc Est. Work Hours", proj.autocalc_estimated_workhours))
    print("%-30s: %s" % ("Active", proj.is_active))

def format_client_entry(cl, verbose=False):
    cl_id = ""
    if args.verbose_list:
        cl_id  = "[%s] " % (cl.id)

    return "* %s%s [Workspace: (%s) Hourly Rate: (%s) Currency: (%s)]" % (cl_id,
            cl.name, cl.workspace.name if cl.workspace is not None else "None", cl.hourly_rate, cl.currency)

def show_client(cl):
    print("%-30s: %d" % ("Client ID", cl.id))
    print("%-30s: %s" % ("Name", cl.name))
    print("%-30s: %s" % ("Workspace", cl.workspace.name if cl.workspace else "None"))
    print("%-30s: %s" % ("Currency", cl.currency))
    print("%-30s: %s" % ("Hourly Rate", cl.hourly_rate))

def format_workspace_entry(wsp, verbose=False):
    wsp_id = ""
    if args.verbose_list:
        wsp_id = "[%s] " % (wsp.id)

    return "* %s%s" % (wsp_id, wsp.name)

def show_workspace(wsp):
    print("%-30s: %d" % ("Workspace ID", wsp.id))
    print("%-30s: %s" % ("Name", wsp.name))
    print("%-30s: %s" % ("Profile Name", wsp.profile_name))
    print("%-30s: %s" % ("Admin", wsp.is_admin))

def format_task_entry(task, verbose=False):
    task_id = ""
    if args.verbose_list:
        task_id = "[%s] " % (task.id)

    return "* %s%s" % (task.id, task.name)

def show_task(task):
    print("%-30s: %d" % ("Task ID", task.id))
    print("%-30s: %s" % ("Name", task.name))
    print("%-30s: %s" % ("Workspace", task.workspace.name if task.workspace else "None"))
    print("%-30s: %s" % ("Project", task.project.name if task.project else "None"))
    print("%-30s: %s" % ("User", task.user.name if task.user else "None"))
    print("%-30s: %s" % ("Estimated Seconds", task.estimated_seconds))
    print("%-30s: %s" % ("Active", task.is_active))

def format_user_entry(user, verbose=False):
    user_id = ""
    if args.verbose_list:
        user_id = "[%s] " % (user.id)
    return "* %s%s <%s>" % (user_id, user.fullname, user.email)

def add_time_entry(args):
    """
    Creates a completed time entry.
    args should be: ENTRY [@PROJECT] DURATION
    """
    
    entry = TogglEntry()

    entry.desc = args.msg
    
    if args.proj is not None:
        entry.project = find_project(args.proj)
        if not entry.project:
            print("Could not find project!")
            return False
    
    # Start and end params
    if args.start is not None:
        entry.start_time = parse_time_str(args.start)
    else:
        entry.start_time = datetime.datetime.utcnow().isoformat()

    if args.end is not None:
        entry.stop_time = parse_time_str(args.end)
    else:
        entry.stop_time = datetime.datetime.utcnow().isoformat()

    # Get the duration.
    if args.duration is not None:
        entry.duration = parse_duration(args.duration)
    else:
        start_time = date_parser.parse(entry.start_time).astimezone(pytz.utc)
        end_time = date_parser.parse(parse_time_str(entry.stop_time)).astimezone(pytz.utc)

        entry.duration = (end_time - start_time).seconds
    
    # Send the data.
    resp = toggl.add_time_entry(entry)

    if args.verbose:
        print(json_format(resp))

    print("New entry added with id %s" % resp.data['id'])
    
    return True

def edit_time_entry(args):
    """Update an existing time entry"""

    if args.verbose:
        print(args)
    # Get an array of objects of recent time data.
    entry = toggl.get_time_entry(args.id)

    if entry is None:
        print("Entry id %s not found!" % args.id)
        return False

    if args.proj != None:
        entry.project = find_project(args.proj)
        if not entry.project:
            print("Could not find project!")
            return False

    if args.msg != None:
        entry.desc = args.msg

    if args.start != None:
        entry.start_time = parse_time_str(args.start)

    if args.end != None:
        entry.stop_time = parse_time_str(args.end)

    # Skip calc if stop time is None - this is the currently active entry.
    if args.calc_duration != False and entry.stop_time is not None:
        start_time = date_parser.parse(entry.start_time).astimezone(pytz.utc)
        end_time = date_parser.parse(parse_time_str(entry.stop_time)).astimezone(pytz.utc)

        entry.duration = (end_time - start_time).seconds
    else:
        if args.duration != None:
            entry.duration = parse_duration(args.duration)

    resp = toggl.update_time_entry(entry)

    return True
            
def parse_time_str(timestr):
    tz = pytz.timezone(toggl_cfg.get('options', 'timezone'))
    tmp = date_parser.parse(timestr)
    if tmp.tzinfo is None:
        tmp = tz.localize(tmp)
    return tmp.astimezone(pytz.utc).isoformat()

def parse_estimate(est):
    if est is None:
        return 0
    mult = 1
    if est.endswith('s'):
        est = est[:-1]
    elif est.endswith('m'):
        mult = 60
        est = est[:-1]
    elif est.endswith('h'):
        mult = 60 * 60
        est = est[:-1]

    return int(est) * mult

def elapsed_time(seconds, suffixes=['y','w','d','h','m','s'], add_s=False, separator=' '):
    """
    Takes an amount of seconds and turns it into a human-readable amount of time.
    From http://snipplr.com/view.php?codeview&id=5713
    """
    # the formatted time string to be returned
    time = []

    # the pieces of time to iterate over (days, hours, minutes, etc)
    # - the first piece in each tuple is the suffix (d, h, w)
    # - the second piece is the length in seconds (a day is 60s * 60m * 24h)
    if toggl_cfg.has_option('options', 'use_mandays') and \
            toggl_cfg.getboolean('options', 'use_mandays') == True:

        parts = [('md', 60 * 60 * 8),
              (suffixes[3], 60 * 60),
              (suffixes[4], 60),
              (suffixes[5], 1)]
    else:
        parts = [(suffixes[0], 60 * 60 * 24 * 7 * 52),
              (suffixes[1], 60 * 60 * 24 * 7),
              (suffixes[2], 60 * 60 * 24),
              (suffixes[3], 60 * 60),
              (suffixes[4], 60),
              (suffixes[5], 1)]
    
    # for each time piece, grab the value and remaining seconds, and add it to
    # the time string
    for suffix, length in parts:
        value = int(seconds / length)
        if value > 0:
            seconds = seconds % length
            time.append('%s%s' % (str(value),
                           (suffix, (suffix, suffix + 's')[value > 1])[add_s]))
        if seconds < 1:
            break
    
    return separator.join(time)

def get_current_time_entry():
    """Returns the current time entry JSON object, or None."""
    entries = get_time_entries()
    
    for entry in entries:
        if int(entry.duration) < 0:
            return entry
    
    return None

def get_time_entries(start=None, end=None):
    """Fetches time entry data and returns it as a Python array."""
    
    tz = pytz.timezone(toggl_cfg.get('options', 'timezone'))

    end_date = None
    # Construct the start and end dates. Toggl seems to want these in UTC.
    if start != None:
        lt = tz.localize(date_parser.parse(args.start))
        end_date = lt.astimezone(pytz.utc)
    else:
        endday = datetime.datetime.now(pytz.utc)
        # Set the default start day to monday
        if endday.weekday() != 0:
            endday = endday - datetime.timedelta(days=endday.weekday())
        end_date = tz.localize(datetime.datetime(endday.year, endday.month, endday.day, 0, 0, 0))
 
    start_date = None
    # The end date is actually earlier in time than start date
    if end != None:
        lt = tz.localize(date_parser.parse(args.end))
        start_date = lt.astimezone(pytz.utc)
    else:
        today = datetime.datetime.now()
        start_date = today.replace(hour=23, minute=59, second=59)
    
    return toggl.get_time_entries(start_date, end_date)

def list_current_time_entry(args):
    """Shows what the user is currently working on (duration is negative)."""
    entry = get_current_time_entry()
    if entry != None:
        print(format_time_entry(entry, verbose=args.verbose_list))
    else:
        print("You're not working on anything right now.")

    return True

def list_projects(args):
    """List all projects."""
    show_archived = False
    if args.show_archived is not None:
        show_archived = args.show_archived
    else:
        if toggl_cfg.has_option('options', 'show_archived_projects'):
            show_archived = toggl_cfg.getboolean('options', 'show_archived_projects')

    raw = None
    if toggl_cache.enabled:
        raw = TogglRawData()
        if not args.update_cache:
            raw.response_data = toggl_cache.read_project_cache()

    proj_list = toggl.get_projects(raw_data=raw)

    if args.update_cache:
        toggl_cache.update_project_cache(raw.response_data)

    wsp = None
    if args.workspace:
        wsp = find_workspace(args.workspace)
        if wsp is None:
            print("Could not find specified workspace!")
            return False

    for proj in proj_list:
        if not proj.is_active and not show_archived:
            continue
        elif wsp is not None and proj.workspace is not None:
            if wsp.id != proj.workspace.id:
                continue
        print(format_project_entry(proj, args.verbose_list))

    return True

def find_project(proj):
    """Find a project given the unique prefix of the name"""
    raw = None
    if toggl_cache.enabled:
        raw = TogglRawData()
        raw.response_data = toggl_cache.read_project_cache()

    proj_list = toggl.get_projects(raw_data=raw)
    if proj.startswith('@') and proj in alias_dict:
        proj = alias_dict[proj]
    for project in proj_list:
        if str(project.id) == proj or project.name.startswith(proj):
            return project
    return None

def list_workspaces(args):
    raw = None
    if toggl_cache.enabled:
        raw = TogglRawData()
        if not args.update_cache:
            raw.response_data = toggl_cache.read_workspace_cache()

    wsp_list = toggl.get_workspaces(raw_data=raw)

    if args.update_cache:
        toggl_cache.update_workspace_cache(raw.response_data)

    for wsp in wsp_list:
        print(format_workspace_entry(wsp, args.verbose_list))
    return True

def find_workspace(wkspc):
    raw = None
    if toggl_cache.enabled:
        raw = TogglRawData()
        raw.response_data = toggl_cache.read_workspace_cache()

    wsp_list = toggl.get_workspaces(raw_data=raw)
    for wsp in wsp_list:
        if str(wsp.id) == wkspc or wsp.name.startswith(wkspc):
            return wsp
    return None

def list_clients(args):
    raw = None
    if toggl_cache.enabled:
        raw = TogglRawData()
        if not args.update_cache:
            raw.response_data = toggl_cache.read_client_cache()

    cl_list = toggl.get_clients(raw_data=raw)

    if args.update_cache:
        toggl_cache.update_client_cache(raw.response_data)

    for cl in cl_list:
        print(format_client_entry(cl, args.verbose_list))

def find_client(client):
    raw = None
    if toggl_cache.enabled:
        raw = TogglRawData()
        raw.response_data = toggl_cache.read_client_cache()

    cli_list = toggl.get_clients(raw_data=raw)
    for cli in cli_list:
        if str(cli.id) == client or cli.name.startswith(client):
            return cli
    return None

def list_tasks(args):
    active = False if args.list_inactive else True
    task_list = toggl.get_tasks(active=active)
    for task in task_list:
        print(format_task_entry(task, args.verbose_list))

def find_task(task):
    task_list = toggl.get_tasks(active=False)
    for task in task_list:
        if str(task.id) == task or task.name.startswith(task):
            return task
    return None

def list_time_entries_date(entries):
    date_fmt = DEFAULT_DATEFMT
    if toggl_cfg.has_option('options', 'datefmt'):
        date_fmt = toggl_cfg.get('options', 'datefmt')

    # Sort the time entries into buckets based on "Month Day" of the entry.
    days = {}
    for entry in entries:
        tz = pytz.timezone(toggl_cfg.get('options', 'timezone'))
        start_time = date_parser.parse(entry.start_time).astimezone(tz).strftime(date_fmt)
        if start_time not in days:
            days[start_time] = []
        days[start_time].append(entry)

    dur_sum = 0
    # For each day, print the entries, then sum the times.
    for date_str in sorted(days.keys()):
        print(date_str)

        duration = 0
        for entry in days[date_str]:
            duration += get_entry_duration(entry)
            if not args.quiet:
                print("   %s" % format_time_entry(entry, verbose=args.verbose_list))
        print("   (%s)" % elapsed_time(int(duration)))
        dur_sum += duration

    if args.sum:
        print("Total time: %s" % elapsed_time(dur_sum))
    return True

def list_time_entries_project(entries):
    projs = {}
    for entry in entries:
        if entry.project == None:
            proj = '(No Project)'
        else:
            proj = entry.project.name
        if proj not in projs:
            projs[proj] = []
        projs[proj].append(entry)
    
    dur_sum = 0
    for proj in projs.keys():
        print("@" + proj)
        duration = 0
        for entry in projs[proj]:
            duration += get_entry_duration(entry)
            if not args.quiet:
                print("   %s" % format_time_entry(entry, show_proj=False, verbose=args.verbose_list))
        print("   (%s)" % (elapsed_time(int(duration))))
        dur_sum += duration

    if args.sum:
        print("Total time: %s" % elapsed_time(dur_sum))
    return True

def filter_match(entry, pattern):
    return re.search(pattern, entry.desc)

def filter_entries(entries, pattern):
    return [e for e in entries if filter_match(e, pattern)]

def list_time_entries(args):
    """Lists all of the time entries from yesterday and today along with
       the amount of time devoted to each.
    """

    # Get an array of objects of recent time data.
    entries = get_time_entries(start=args.start, end=args.end)

    if args.grep:
        entries = filter_entries(entries, args.grep)

    if args.proj:
        list_time_entries_project(entries)
    else:
        list_time_entries_date(entries)

def parse_duration(str):
    """Parses a string of the form [[Hours:]Minutes:]Seconds and returns
       the total time in seconds as an integer.
    """
    elements = str.split(':')
    duration = 0
    if len(elements) == 3:
        duration += int(elements[0]) * 3600
        elements = elements[1:]
    if len(elements) == 2:
        duration += int(elements[0]) * 60
        elements = elements[1:]
    duration += int(elements[0])

    return duration

def get_entry_duration(entry):
    e_time = 0
    if entry.duration >= 0:
        e_time = int(entry.duration)
    else:
        is_running = '* '
        e_time = (datetime.datetime.now(pytz.utc) - date_parser.parse(entry.start_time).astimezone(pytz.utc)).seconds
    return e_time

def delete_time_entry(args):
    entry_id = args.id

    print("Deleting entry %s" % entry_id)

    if not toggl.delete_time_entry(entry_id):
        print("Entry %s does not exist!" % entry_id)
        return False

    return True

def start_time_entry(args):
    """Starts a new time entry."""
    
    entry = TogglEntry()
    entry.desc = args.msg

    # See if we have a @project.
    if args.proj is not None:
        entry.project = find_project(args.proj)
        if not entry.project:
            print("Could not find project!")
            return False

    start_time = None
    if args.time != None:
        start_time = parse_time_str(args.time)
    else:
        start_time = datetime.datetime.utcnow().isoformat()

    entry.start_time = start_time
    entry.stop_time = None
    entry.duration = -1

    resp = toggl.add_time_entry(entry)

    if args.verbose:
        print(json_format(resp.data))

    print("New entry started with id %s" % resp.data['id'])
    
    return True

def stop_time_entry(args):
    """Stops the current time entry (duration is negative)."""

    entry = get_current_time_entry()
    if entry != None:
        # Get the start time from the entry, converted to UTC.
        start_time = date_parser.parse(entry.start_time).astimezone(pytz.utc)

        if args.time:
            tz = pytz.timezone(toggl_cfg.get('options', 'timezone'))
            stop_time = tz.localize(date_parser.parse(args.time)).astimezone(pytz.utc)
        else:
            # Get stop time(now) in UTC.
            stop_time = datetime.datetime.now(pytz.utc)

        # Create the payload.
        entry.stop_time = stop_time.isoformat()
        entry.duration = (stop_time - start_time).seconds

        toggl.update_time_entry(entry)

    else:
        print("You're not working on anything right now.")
        return False

    return True

def cmd_project(args):
    if args.add:
        if not args.name or not args.workspace:
            print("-n and -w are required when creating a new project")
            return False

        wksp = find_workspace(args.workspace)
        if wksp is None:
            print("Could not find specified workspace!")
            return False

        p = TogglProject()
        p.name = args.name
        p.billable = args.billable
        p.estimated_workhours = args.estimated_workhours
        p.autocalc_estimated_workhours = args.auto_calc
        p.workspace = wksp

        if args.client is not None:
            cli = find_client(args.client)
            if cli is None:
                print("Could not find specified client!")
                return False
            p.client = cli

        toggl.add_project(p)
    elif args.update:
        if not args.id:
            print("-i is required when updating a project")
            return False

        p = find_project(args.id)
        if p is None:
            print("Could not find specified project!")
            return False
        if args.name is not None:
            p.name = args.name
        if args.billable is not None:
            p.billable = args.billable
        if args.estimated_workhours is not None:
            p.estimated_workhours = args.estimated_workhours
        if args.auto_calc is not None:
            p.autocalc_estimated_workhours = args.auto_calc
        if args.workspace is not None:
            wksp = find_workspace(args.workspace)
            if wksp is None:
                print("Could not find specified workspace!")
                return False
            p.workspace = wksp
        if args.client is not None:
            cli = find_client(args.client)
            if cli is None:
                print("Could not find specified client!")
                return False
            p.client = cli

        toggl.update_project(p)
    elif args.archive:
        toggl.archive_projects(args.archive)
    elif args.reopen:
        toggl.reopen_projects(args.reopen)
    elif args.id:
        proj = find_project(args.id)
        if proj is None:
            print("Could not find specified project!")
            return False
        else:
            show_project(proj)
    else:
        list_projects(args)

    return True

def cmd_workspace(args):
    if args.user_list:
        if not args.id:
            print("Workspace ID is required to list users!")
            return False
        user_list = toggl.get_workspace_users(args.id)
        for user in user_list:
            print(format_user_entry(user))
        print("Total Users: %d" % len(user_list))
    elif args.id:
        wsp = find_workspace(args.id)
        if wsp is None:
            print("Could not find specified workspace!")
            return False
        else:
            show_workspace(wsp)
    else:
        list_workspaces(args)

    return True

def cmd_client(args):
    if args.add:
        if not args.name:
            print("Name is required to add a new client!")
            return False

        c = TogglClient()
        c.name = args.name
        c.hourly_rate = args.rate
        c.currency = args.currency
        if args.workspace:
            wksp = find_workspace(args.workspace)
            if not wksp:
                print("Unable to find specified workspace!")
                return False
            c.workspace = wksp

        toggl.add_client(c)

        return True
    elif args.update:
        c = None
        if not args.id:
            print("You must specify the id of the client to update!")
            return False
        c = find_client(args.id)
        if not c:
            print("Unable to find specified client!")
            return False
        if args.name is not None:
            c.name = args.name
        if args.rate is not None:
            c.hourly_rate = args.rate
        if args.currency is not None:
            c.currency = args.currency
        if args.workspace is not None:
            wksp = find_workspace(args.workspace)
            if not wksp:
                print("Unable to find specified workspace!")
                return False
            c.workspace = wksp

        if not toggl.update_client(c):
            print("Failed to update specified client!")
            return False

        return True
    elif args.delete:
        if not args.id:
            print("Must specify the client id to delete!")
            return False

        if not toggl.delete_client(args.id):
            print("Failed to update specified client!")
            return False

        return True
    elif args.id:
        cl = find_client(args.id)
        if cl is None:
            print("Could not find specified client!")
            return False
        else:
            show_client(cl)
        return True
    else:
        list_clients(args)

def cmd_task(args):
    if args.add:
        if not args.name:
            print("Name is required for new task entries!")
            return False
        elif not args.proj:
            print("Project is required for new task entries!")
            return False

        proj = find_project(args.proj)
        if not proj:
            print("Unable to find specified project!")
            return False

        if not check_feature_support(proj):
            print("Your account does not support this feature.")
            return False

        t = TogglTask()

        t.name = args.name
        t.is_active = args.active if args.active is not None else True
        t.estimated_seconds = parse_estimate(args.estimate)

        t.project = proj

        toggl.add_task(t)

        return True
    elif args.update:
        if not args.id:
            print("You must specify the id of a task to update!")
            return False
        t = find_task(args.id)
        if not t:
            print("Unable to find specified task!")
            return False

        if args.name:
            t.name = args.name
        if args.active is not None:
            t.is_active = args.active
        if args.estimate is not None:
            t.estimated_seconds = parse_estimate(args.estimate)
        if args.proj is not None:
            proj = find_project(args.proj)
            if not proj:
                print("Unable to find specified project!")
                return False
            t.project = proj

        toggl.update_task(t)

        return True
    elif args.delete:
        if not args.id:
            print("You must specify the id of a task to delete!")
            return False

        toggl.delete_task(args.id)

        return True
    elif args.id:
        task = find_task(args.id)
        if task is None:
            print("Could not find specified task!")
            return False
        else:
            show_task(task)
        return True
    else:
        list_tasks(args)

def cmd_update(args):
    if not toggl_cfg.has_option('options', 'cache_enabled') or \
            not toggl_cfg.getboolean('options', 'cache_enabled'):
        print("Caching is not enabled. Set options.cache_enabled in ~/.togglrc to enable it.")
        return False

    raw = TogglRawData()
    toggl.get_projects(raw_data=raw)
    toggl_cache.update_project_cache(raw.response_data)

    raw = TogglRawData()
    toggl.get_workspaces(raw_data=raw)
    toggl_cache.update_workspace_cache(raw.response_data)

    raw = TogglRawData()
    toggl.get_clients(raw_data=raw)
    toggl_cache.update_client_cache(raw.response_data)

    print("Caches updated!")
    return True

def visit_web(args):
    if not toggl_cfg.has_option('options', 'web_browser_cmd'):
        print("Please set the web_browser_cmd setting in the options section of your ~/.togglrc")
    else:
        os.system(toggl_cfg.get('options', 'web_browser_cmd') + ' ' + WWW_ADDRESS)

def create_default_cfg():
    cfg = configparser.RawConfigParser()
    cfg.add_section('auth')
    cfg.set('auth', 'username', 'user@example.com')
    cfg.set('auth', 'password', 'secretpasswd')
    cfg.add_section('options')
    cfg.set('options', 'ignore_start_times', 'False')
    cfg.set('options', 'timezone', 'UTC')
    cfg.set('options', 'web_browser_cmd', 'w3m')
    cfg.set('options', 'datefmt', DEFAULT_DATEFMT)
    cfg.set('options', 'entry_datefmt', DEFAULT_ENTRY_DATEFMT)
    cfg.set('options', 'use_mandays', False)
    cfg.set('options', 'show_archived_projects', False)
    cfg.set('options', 'max_cache_age_days', 0)
    with open(os.path.expanduser('~/.togglrc'), 'w') as cfgfile:
        cfg.write(cfgfile)

def find_alias_key_by_val(sval):
    for key, val in alias_dict.items():
        if val == sval:
            return key
    return None

def build_alias_table():
    for pair in toggl_cfg.items('aliases'):
        alias_dict[pair[0]] = pair[1]

def init_config():
    global toggl_cfg
    try:
        toggl_cfg = configparser.ConfigParser(interpolation=None)
    except:
        toggl_cfg = configparser.ConfigParser()

    toggl_cfg.optionxform = lambda option: option
    if toggl_cfg.read(os.path.expanduser('~/.togglrc')) == []:
        create_default_cfg()
        print("Missing ~/.togglrc. A default has been created for editing.")
        return False

    if toggl_cfg.has_section('aliases'):
        build_alias_table()

    return True

def init_cache():
    global toggl_cache
    cache_enabled = False
    if toggl_cfg.has_option('options', 'cache_enabled'):
        cache_enabled = toggl_cfg.getboolean('options', 'cache_enabled')
    cache_path = DEFAULT_CACHE_PATH
    if toggl_cfg.has_option('options', 'cache_path'):
        cache_path = toggl_cfg.get('options', 'cache_path')
    max_cache_age = 0
    if toggl_cfg.has_option('options', 'max_cache_age_days'):
        max_cache_age = toggl_cfg.get('options', 'max_cache_age_days')
    toggl_cache = TogglCache(cache_path=cache_path,
            cache_enabled=cache_enabled, max_age_days=float(max_cache_age))

    return True

def main():
    """Program entry point."""
    
    if not init_config() or not init_cache():
        return 1

    global IGNORE_START_TIMES
    auth = (toggl_cfg.get('auth', 'username').strip(), toggl_cfg.get('auth', 'password').strip())
    IGNORE_START_TIMES = toggl_cfg.getboolean('options', 'ignore_start_times')

    parser = argparse.ArgumentParser(prog='toggl')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')

    subparsers = parser.add_subparsers(help='sub-command help')

    parser_ls = subparsers.add_parser('ls', help='List time entries')
    parser_ls.add_argument('-p', '--proj', help='Sort entries by project', action='store_true', default=False)
    parser_ls.add_argument('-s', '--start', help='Specify start date', default=None)
    parser_ls.add_argument('-e', '--end', help='Specify end date', default=None)
    parser_ls.add_argument('-g', '--grep', help='Find time entry descriptions matching this regex', default=None)
    parser_ls.add_argument('-v', '--verbose-list', help='Show verbose output', action='store_true', default=False)
    parser_ls.add_argument('-q', '--quiet', help='Do not show entries, only sums', action='store_true', default=False)
    parser_ls.add_argument('-S', '--sum', help='Show time summary', action='store_true', default=False)
    parser_ls.set_defaults(func=list_time_entries)

    parser_add = subparsers.add_parser('add', help='Add a new time entry')
    parser_add.add_argument('-m', '--msg', help='Log entry message', required=True)
    parser_add.add_argument('-p', '--proj', help='Project for the log entry', default=None)
    parser_add.add_argument('-s', '--start', help='Specify start date', default=None)
    parser_add.add_argument('-e', '--end', help='Specify end date', default=None)
    parser_add.add_argument('-d', '--duration', help='Entry duration', required=False)
    parser_add.set_defaults(func=add_time_entry)

    parser_edit = subparsers.add_parser('edit', help='Edit an existing time entry')
    parser_edit.add_argument('-i', '--id', help='The time entry id to edit', required=True)
    parser_edit.add_argument('-m', '--msg', help='Log entry message')
    parser_edit.add_argument('-p', '--proj', help='Project for the log entry')
    parser_edit.add_argument('-d', '--duration', help='Entry duration')
    parser_edit.add_argument('-s', '--start', help='Specify start date', default=None)
    parser_edit.add_argument('-e', '--end', help='Specify end date', default=None)
    parser_edit.add_argument('-c', '--calc-duration', help='Calculate duration from start/end dates', action='store_true', default=False)
    parser_edit.set_defaults(func=edit_time_entry)

    parser_now = subparsers.add_parser('now', help='Show the current time entry')
    parser_now.add_argument('-v', '--verbose-list', help='Show verbose output', action='store_true', default=False)
    parser_now.set_defaults(func=list_current_time_entry)

    parser_proj = subparsers.add_parser('proj', help='Manage projects')
    parser_proj.add_argument('-l', '--list', help="List projects", action='store_true', default=False)
    parser_proj.add_argument('-A', '--show-archived', help="Override the show-archived setting", action='store_true', default=None)
    parser_proj.add_argument('-a', '--add', help="Add a new project entry", action='store_true', default=False)
    parser_proj.add_argument('-u', '--update', help="Update an existing project entry", action='store_true', default=False)
    parser_proj.add_argument('-r', '--archive', help="Archive a project entry", default=None, metavar='IDLIST')
    parser_proj.add_argument('-o', '--reopen', help="Reopen an archived project entry", default=None, metavar='IDLIST')
    parser_proj.add_argument('-b', '--billable', help="Set the project's billable value", type=bool, default=None, choices=[True, False])
    parser_proj.add_argument('-n', '--name', help="Set the project's name", default=None)
    parser_proj.add_argument('-i', '--id', help="Specify the project id", default=None)
    parser_proj.add_argument('-c', '--client', help="Set the project's client", default=None, metavar='NAME/ID')
    parser_proj.add_argument('-w', '--workspace', help="Set the project's workspace", default=None, metavar='NAME/ID')
    parser_proj.add_argument('-e', '--estimated-workhours', help="Set the project's estimated work hours", type=int, default=None)
    parser_proj.add_argument('-C', '--auto-calc', help="Automatically calculate estimated work hours", type=bool, default=None)
    parser_proj.add_argument('-U', '--update-cache', help="Update the project cache", action='store_true', default=False)
    parser_proj.add_argument('-v', '--verbose-list', help='Show verbose output', action='store_true', default=False)
    parser_proj.set_defaults(func=cmd_project)

    parser_start = subparsers.add_parser('start', help='Start a new time entry')
    parser_start.add_argument('-m', '--msg', help='Log entry message', required=True)
    parser_start.add_argument('-p', '--proj', help='Project for the log entry')
    parser_start.add_argument('-t', '--time', help='Specify the start date and/or time')
    parser_start.set_defaults(func=start_time_entry)

    parser_stop = subparsers.add_parser('stop', help='Start a new time entry')
    parser_stop.add_argument('-t', '--time', help='Specify the stop time')
    parser_stop.set_defaults(func=stop_time_entry)

    parser_www = subparsers.add_parser('www', help='Open the webpage')
    parser_www.set_defaults(func=visit_web)

    parser_rm = subparsers.add_parser('rm', help='Remove a time entry')
    parser_rm.add_argument('-i', '--id', help='The id to remove', required=True)
    parser_rm.set_defaults(func=delete_time_entry)

    parser_wspace = subparsers.add_parser('wksp', help='List workspaces')
    parser_wspace.add_argument('-i', '--id', help='The workspace id')
    parser_wspace.add_argument('-l', '--list', help='List workspaces', action='store_true', default=False)
    parser_wspace.add_argument('-u', '--user-list', help='List workspace users', action='store_true', default=False)
    parser_wspace.add_argument('-U', '--update-cache', help="Update the workspace cache", action='store_true', default=False)
    parser_wspace.add_argument('-v', '--verbose-list', help='Show verbose output', action='store_true', default=False)
    parser_wspace.set_defaults(func=cmd_workspace)

    parser_clients = subparsers.add_parser('client', help='Manage clients')
    parser_clients.add_argument('-l', '--list', help='List clients', action='store_true', default=False)
    parser_clients.add_argument('-a', '--add', help='Add a new client entry', action='store_true', default=False)
    parser_clients.add_argument('-u', '--update', help='Update an existing client entry', action='store_true', default=False)
    parser_clients.add_argument('-D', '--delete', help='Add a new client entry', action='store_true', default=False)
    parser_clients.add_argument('-i', '--id', help='The client id', default=None)
    parser_clients.add_argument('-n', '--name', help="Set the clients's name", default=None)
    parser_clients.add_argument('-c', '--currency', help='Set the currency', default=None)
    parser_clients.add_argument('-r', '--rate', help='Set the hourly rate', default=None)
    parser_clients.add_argument('-w', '--workspace', help='Set the workspace for this client', default=None)
    parser_clients.add_argument('-U', '--update-cache', help="Update the workspace cache", action='store_true', default=False)
    parser_clients.add_argument('-v', '--verbose-list', help='Show verbose output', action='store_true', default=False)
    parser_clients.set_defaults(func=cmd_client)

    parser_tasks = subparsers.add_parser('task', help='Manage tasks')
    parser_tasks.add_argument('-l', '--list', help='List tasks', action='store_true', default=False)
    parser_tasks.add_argument('-I', '--list-inactive', help='Include inactive tasks in list', action='store_true', default=False)
    parser_tasks.add_argument('-a', '--add', help='Add a new task entry', action='store_true', default=False)
    parser_tasks.add_argument('-u', '--update', help='Update an existing task entry', action='store_true', default=False)
    parser_tasks.add_argument('-D', '--delete', help='Add a new task entry', action='store_true', default=False)
    parser_tasks.add_argument('-i', '--id', help='The task id', default=None)
    parser_tasks.add_argument('-n', '--name', help='Set the task name', default=None)
    parser_tasks.add_argument('-p', '--proj', help='Project for the task entry', default=None)
    parser_tasks.add_argument('-U', '--user', help="Set the task's user ", default=None)
    parser_tasks.add_argument('-e', '--estimate', help="Set the task estimate [int, suffix with s, m, or h]", default=None)
    parser_tasks.add_argument('-A', '--active', help='Set the task active status', choices=[True, False], default=None)
    parser_tasks.add_argument('-v', '--verbose-list', help='Show verbose output', action='store_true', default=False)
    parser_tasks.set_defaults(func=cmd_task)

    parser_update = subparsers.add_parser('update', help='Update caches')
    parser_update.set_defaults(func=cmd_update)

    global args
    args = parser.parse_args(sys.argv[1:])
    global toggl
    toggl = TogglApi(url=TOGGL_URL, auth=auth, verbose=args.verbose)

    if args.func(args):
        return 0
    else:
        return 1

if __name__ == "__main__":
    sys.exit(main())

# vim: set ts=4 sw=4 tw=0 :
