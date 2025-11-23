#!/usr/bin/env python3
#-*- coding: utf-8 -*-

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""
Script for exporting tracks through audioscrobbler API.
Usage: lastexport.py -u USER [-o OUTFILE] [-p STARTPAGE] [-s SERVER]
"""

import urllib.request
import urllib.parse
import sys
import time
import re
import xml.etree.ElementTree as ET
from optparse import OptionParser

__version__ = '0.0.4'
original_script = 'kabniel (https://github.com/kabniel/last2libre)'

def get_options(parser):
    parser.add_option("-u", "--user", dest="username", default=None,
                      help="User name.")
    parser.add_option("-o", "--outfile", dest="outfile", default="exported_tracks.txt",
                      help="Output file, default is exported_tracks.txt")
    parser.add_option("-p", "--page", dest="startpage", type="int", default=1,
                      help="Page to start fetching tracks from, default is 1")
    parser.add_option("-s", "--server", dest="server", default="last.fm",
                      help="Server to fetch track info from, default is last.fm")
    parser.add_option("-t", "--type", dest="infotype", default="scrobbles",
                      help="Type of information to export, scrobbles|loved|banned, default is scrobbles")
    options, args = parser.parse_args()

    if not options.username:
        sys.exit("User name not specified, see --help")

    if options.infotype == "loved":
        infotype = "lovedtracks"
    elif options.infotype == "banned":
        infotype = "bannedtracks"
    else:
        infotype = "recenttracks"
         
    return options.username, options.outfile, options.startpage, options.server, infotype

def connect_server(server, username, startpage, sleep_func=time.sleep, tracktype='recenttracks'):
    if server == "libre.fm":
        baseurl = 'http://alpha.libre.fm/2.0/?'
        urlvars = {'method': 'user.get%s' % tracktype,
                    'api_key': ('lastexport.py-%s' % __version__).ljust(32, '-'),
                    'user': username,
                    'page': startpage,
                    'limit': 200}

    elif server == "last.fm":
        baseurl = 'http://ws.audioscrobbler.com/2.0/?'
        urlvars = {'method': 'user.get%s' % tracktype,
                    'api_key': 'e38cc7822bd7476fe4083e36ee69748e',
                    'user': username,
                    'page': startpage,
                    'limit': 50}
    else:
        if server[:7] != 'http://':
            server = 'http://%s' % server
        baseurl = server + '/2.0/?'
        urlvars = {'method': 'user.get%s' % tracktype,
                    'api_key': ('lastexport.py-%s' % __version__).ljust(32, '-'),
                    'user': username,
                    'page': startpage,
                    'limit': 200}
        
    url = baseurl + urllib.parse.urlencode(urlvars)
    
    last_exc = None
    for interval in (1, 5, 10, 62):
        try:
            with urllib.request.urlopen(url) as f:
                response = f.read()
            break
        except Exception as e:
            last_exc = e
            print("Exception occured, retrying in %ds: %s" % (interval, e))
            sleep_func(interval)
    else:
        print("Failed to open page %s" % urlvars['page'])
        raise last_exc

    response = response.decode('utf-8', 'ignore')
    response = re.sub('\xef\xbf\xbe', '', response)
    
    return response

def get_pageinfo(response, tracktype='recenttracks'):
    xmlpage = ET.fromstring(response)
    totalpages = xmlpage.find(tracktype).attrib.get('totalPages')
    return int(totalpages)

def get_tracklist(response):
    xmlpage = ET.fromstring(response)
    tracklist = xmlpage.iter('track')
    return tracklist

def parse_track(trackelement):
    artist_element = trackelement.find('artist')
    if artist_element is not None and list(artist_element):
        artistname = artist_element.find('name').text
        artistmbid = artist_element.find('mbid').text
    elif artist_element is not None:
        artistname = artist_element.text
        artistmbid = artist_element.get('mbid')
    else:
        artistname = ''
        artistmbid = ''

    album_element = trackelement.find('album')
    if album_element is None:
        albumname = ''
        albummbid = ''
    else:
        albumname = album_element.text
        albummbid = album_element.get('mbid')

    trackname = trackelement.find('name').text
    trackmbid = trackelement.find('mbid').text
    date = trackelement.find('date').get('uts')

    output = [date, trackname, artistname, albumname, trackmbid, artistmbid, albummbid]

    for i, v in enumerate(output):
        if v is None:
            output[i] = ''

    return output

def write_tracks(tracks, outfileobj):
    for fields in tracks:
        outfileobj.write("\t".join(fields) + "\n")

def get_tracks(server, username, startpage=1, sleep_func=time.sleep, tracktype='recenttracks'):
    page = startpage
    response = connect_server(server, username, page, sleep_func, tracktype)
    totalpages = get_pageinfo(response, tracktype)

    if startpage > totalpages:
        raise ValueError("First page (%s) is higher than total pages (%s)." % (startpage, totalpages))

    while page <= totalpages:
        if page > startpage:
            response =  connect_server(server, username, page, sleep_func, tracktype)

        tracklist = get_tracklist(response)
		
        tracks = []
        for trackelement in tracklist:
            if "nowplaying" not in trackelement.attrib or not trackelement.attrib["nowplaying"]:
                tracks.append(parse_track(trackelement))

        yield page, totalpages, tracks

        page += 1
        sleep_func(.5)

def main(server, username, startpage, outfile, infotype='recenttracks'):
    trackdict = {}
    page = startpage
    totalpages = -1
    n = 0
    try:
        for page, totalpages, tracks in get_tracks(server, username, startpage, tracktype=infotype):
            print("Got page %s of %s.." % (page, totalpages))
            for track in tracks:
                if infotype == 'recenttracks':
                    trackdict.setdefault(track[0], track)
                else:
                    n += 1
                    trackdict.setdefault(n, track)
    except ValueError as e:
        sys.exit(e)
    except Exception:
        raise
    finally:
        with open(outfile, 'a', encoding='utf-8') as outfileobj:
            tracks = sorted(trackdict.values(), reverse=True)
            write_tracks(tracks, outfileobj)
            print("Wrote page %s-%s of %s to file %s" % (startpage, page, totalpages, outfile))
            print("original script: kabniel (https://github.com/kabniel/last2libre)")

if __name__ == "__main__":
    parser = OptionParser()
    username, outfile, startpage, server, infotype = get_options(parser)
    main(server, username, startpage, outfile, infotype)
