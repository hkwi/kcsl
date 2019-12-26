import csv
import contextlib
import datetime
import re
import io
import logging
import lxml.html
import os.path
import requests
import rdflib
import pdftableextract as pte
import pical
import yaml
import unicodedata
from email.utils import parsedate
from urllib.request import urlopen
from urllib.parse import urlparse
from rdflib.namespace import *
from . import pdf_tool2

NS1 = rdflib.Namespace("http://hkwi.github.io/kcsl/terms#")


_holidays = set()
def holidays():
	_ = "to"
	info = [
		(2016, 11,  3),
		(2016, 11, 23),
		(2016, 12, 22, _, 31),
		(2017,  1,  1, _, 10),
		(2017,  3, 20),
		(2017,  3, 22, _, 31),
		(2017,  4,  1, _, 16),
		(2017,  5,  3, _,  7),
		(2017,  7, 17),
		(2017,  7, 21, _, 31),
		(2017,  9, 1),
		(2017,  9, 18),
		(2017, 10,  9),
		(2017, 11,  3),
		(2017, 11, 23),
		(2017, 12, 23, _, 31),
		(2018,  1,  1, _,  9),
		(2018,  3, 20, _, 31),
		(2018,  2, 12), # 振替休日
		(2018,  4,  1, _, 12),
		(2018,  4, 30),
		(2018,  5,  3, _,  6),
		(2018,  7, 16),
		(2018,  7, 20, _, 31),
		(2018,  9,  1, _,  4),
		(2018,  9, 17),
		(2018,  9, 24),
		(2018, 10,  8),
		(2018, 11, 23),
		(2018, 12, 22, _, 31),
		(2019,  1,  1, _, 7),
		(2019,  1, 14),
		(2019,  2, 11),
		(2019,  3, 20, _, 31),
		(2019,  4,  1, _, 11),
		(2019,  4, 29, _, 30),
		(2019,  5,  1, _,  6),
		(2019,  7, 15),
		(2019,  7, 19, _, 31),
		(2019,  9,  1, _, 2),
		(2019,  9, 16),
		(2019,  9, 23),
		(2019, 10, 14),
		(2019, 10, 22),
		(2019, 11,  4),
		(2019, 12, 25, _, 31),
		(2020,  1,  1, _,  7),
		(2020,  1, 13),
	]
	_holidays = []
	for i in info:
		if len(i) == 3:
			_holidays.append(datetime.date(*i))
		elif len(i) == 5 and i[3] == _:
			assert i[2] < i[4]
			_holidays += [datetime.date(i[0], i[1], i[2]+x)
				for x in range(i[4]-i[2]+1)]
	
	return _holidays

def get_days(year, month):
	head = datetime.date(int(year), int(month), 1)
	days = []
	for i in range(31):
		o = head + datetime.timedelta(days=i)
		if o.year == head.year and o.month == head.month and o.weekday() < 5 and o not in holidays():
			days.append(o)
	return days

def main():
	#base = "http://www.city.kobe.lg.jp/child/school/lunch/kyusyoku/kondate_shiyousyokuhin.html"
	base = "http://www.city.kobe.lg.jp/a54017/kosodate/gakko/school/lunch/kyusyoku/kondatehyo.html"
	fp = urlopen(base)
	r = lxml.html.parse(fp).getroot()
	r.make_links_absolute()
	for anchor in r.xpath('//*[@id="tmp_contents"]//a'):
		href = anchor.get("href")
		if re.search(r"/\d+\-[^/]+$", href): # 献立表に違いない
			month_match = re.search("(\d+)月", list(anchor.xpath("preceding::h2/text()"))[-1])
			if month_match:
				month = month_match.group(1)
				proc(href, anchor_text=anchor.text, month=int(month))

@contextlib.contextmanager
def _history(filename):
	g = rdflib.Graph()
	if os.path.exists(filename):
		g.load(filename, format="turtle")
	yield g
	if filename:
		with open(filename, "wb") as dst:
			g.serialize(destination=dst, format="turtle")


def year_for(month, found=None):
	if found is None:
		found = datetime.date.today()
	
	if found.month > 9 and month < 3:
		return found.year + 1
	elif found.month < 3 and month > 9:
		return found.year - 1
	else:
		return found.year

assert year_for(1, datetime.date(2017, 2, 1)) == 2017
assert year_for(2, datetime.date(2017, 2, 1)) == 2017
assert year_for(3, datetime.date(2017, 2, 1)) == 2017 # 
assert year_for(11, datetime.date(2016,11, 1)) == 2016
assert year_for(11, datetime.date(2016,12, 1)) == 2016
assert year_for(11, datetime.date(2017, 1, 1)) == 2016
assert year_for(6, datetime.date(2017, 7, 1)) == 2017
assert year_for(6, datetime.date(2017, 6, 1)) == 2017
assert year_for(6, datetime.date(2017, 5, 1)) == 2017
assert year_for(1, datetime.date(2018, 12, 1)) == 2019
assert year_for(12, datetime.date(2019, 1, 1)) == 2018

class PdfStore(object):
	def __init__(self, url, base=None):
		self.url = url
		
		m = re.match("(\d+)-(.*).pdf", os.path.basename(urlparse(url).path))
		assert m, url
		
		month, self.group = m.groups()
		self.month = int(month)
		
		if base is None:
			base = datetime.date.today()
		
		self.year = year_for(self.month, base)
	
	def path(self, ext):
		return "data/{:04d}-{:02d}-{:s}.{:s}".format(self.year, self.month, self.group, ext)
	
	def local(self, ext):
		return "docs/" + self.path(ext)
	
	def remote(self, ext):
		return "http://hkwi.github.com/kcsl/" + self.path(ext)


def download(url, history=None):
	fs = PdfStore(url)
	with _history(history) as g:
		lm = g.value(rdflib.URIRef(url), NS1["last-modified"])
		
		fp = None
		if os.path.exists(fs.local("pdf")) and lm:
			fp = requests.get(url, headers={"If-Modified-Since":lm})
			if fp.status_code == 304: # xxx: not modified
				return
		
		if fp is None:
			fp = requests.get(url)
		
		if not fp.ok:
			return
		
		logging.info("downloading %s" % url)
		os.makedirs(os.path.dirname(fs.local("pdf")), exist_ok=True)
		with open(fs.local("pdf"), "wb") as w:
			for data in fp:
				w.write(data)
		
		g.set((rdflib.URIRef(url), NS1["mirror"], rdflib.URIRef(fs.remote("pdf"))))
		lm = fp.headers.get("last-modified")
		if lm:
			g.set((rdflib.URIRef(url), NS1["last-modified"], rdflib.Literal(lm)))

def auto_menu2(url, g, base=None):
	fs = PdfStore(url, base)
	return list(pdf_tool2.pdf_tok(fs.local("pdf")))

def auto_menu(url, g, base=None):
	fs = PdfStore(url, base)
	if not os.path.exists(fs.local("csv")):
		with open(fs.local("csv"), "w", encoding="UTF-8") as w:
			csv.writer(w).writerows(
				pte.table_to_list(
					pte.process_page(fs.local("pdf"), "1", whitespace="raw", bitmap_resolution=600), 1)[1])
	if g:
		g.set((rdflib.URIRef(url), NS1["csv"], rdflib.URIRef(fs.remote("csv"))))
	
	rs = [r for r in csv.reader(open(fs.local("csv"), encoding="UTF-8"))]
	menus = []
	slot = None
	mask = None
	skip_in_cell = 0
	for i,r in enumerate(rs):
		for j,c in enumerate(r):
			c = c.replace("\u20dd", "\u25cb")
			c = c.encode("CP932", "ignore").decode("CP932", "ignore")
			c = re.sub("[ \t　]", "", c).strip()
			lines = [l.strip() for l in c.split() if l.strip()]
			if "こんだて" in lines:
				if slot:
					menus += [slot[k] for k in sorted(slot.keys()) if k not in mask]
				slot = {}
				mask = set()
				try:
					skip_in_cell = lines.index("こんだて")
				except ValueError:
					skip_in_cell = 0
			elif "おかず" in lines:
				if slot:
					menus += [slot[k] for k in sorted(slot.keys()) if k not in mask]
				slot = None
			elif slot is not None:
				content = re.sub("[\s　]", "", c)
				
				if "エネルギー" in content:
					mask.add(j)
				elif "お知らせ" in content:
					mask.add(j)
				elif "特別支援学校" in content:
					mask.add(j)
				elif PdfStore(url).month == datetime.date(2016,12,1):
					if "地区１２月１４日" in content:
						mask.add(j)
					elif "\u202c" in content:
						mask.add(j)
				
				if "とんじゃ" in content:
					print(content)
				
				if "です。" in c:
					mask.add(j)
				
				if content:
					ts = [re.sub("[\s　]","",u).strip() for u in c.split("\n")]
					if skip_in_cell:
						ts = ts[skip_in_cell:]
					
					ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
					if j in slot:
						slot[j] += [t for t in ts if t and t not in ALPHABET]
					else:
						slot[j] = [t for t in ts if t and t not in ALPHABET]
	if slot:
		menus += [slot[k] for k in sorted(slot.keys()) if k not in mask]
	
	menus = [m for m in menus if not re.match(r"^[\(\)（）]+$", "".join(m))]
	return menus

gmenus = set()

def proc(url, **kwargs):
	rec = "docs/record.ttl"
	download(url, history=rec)
	with _history(rec) as g:
		lm = g.value(rdflib.URIRef(url), NS1["last-modified"])
		if lm:
			tm = datetime.datetime(*parsedate(lm.value)[:6])
			fs = PdfStore(url, tm)
		else:
			fs = PdfStore(url)
		
		# hand-crafted yaml
		if os.path.exists(fs.local("yml")):
			menus = yaml.load(open(fs.local("yml")))
		else:
			menus = auto_menu2(url, g)
			opts = dict(allow_unicode=True, explicit_start=True, default_flow_style=None)
			print(yaml.dump(menus, **opts))
			print(yaml.dump(menus, open(fs.local("yml"), "w"), **opts))
			for m in menus:
				gmenus.update(set(m))
		
		yaml_to_ics(fs.local("yml"), "docs/%s.ics" % fs.group, tm=tm)


def yaml_to_ics(yaml_path, ics_path, tm=None):
	# YAML
	f = re.search(r"(\d{4})-(\d{2})-(.+).yml$", yaml_path)
	assert f, yaml_path
	year, month, yaml_grp = f.groups()
	menus = yaml.load(open(yaml_path))
	days = get_days(year, month)
	
	assert len(days) == len(menus), "days=%d menus=%d" % (len(days), len(menus))
	
	# ICS
	f = re.search(r"([^/]+).ics$", ics_path)
	assert f, yaml_path
	ics_grp = f.group(1)
	
	# YAML => ICS
	r = pical.parse(open(ics_path, "rb"))[0]
	for d,m in zip(days, menus):
		if tm is None:
			tm = datetime.datetime.fromtimestamp(os.stat(yaml_path).st_mtime)
		
		props = [
			("UID", "%s@%s" % (d.isoformat(), yaml_grp), []),
			("DTSTAMP", tm, []),
			("DTSTART", d, [("VALUE",["DATE"])]),
			("SUMMARY", ",".join(m), []),
			("DESCRIPTION", "\n".join(m), []),
		]
		
		ev = None
		for c in r.children:
			if d == c["DTSTART"]:
				f = re.match("(\d{4})-(\d{2})-(\d{2})@(.+)", c["UID"])
				y,m,d,g = f.groups()
				
				if y==year and m==month and g==yaml_grp:
					ev = c
					lut = {p[0]:p[1] for p in props}
					if ev["SUMMARY"] != lut["SUMMARY"] or ev["DESCRIPTION"] != lut["DESCRIPTION"]:
						ev.properties = props
				else:
					ev = "skip"
		
		if ev is None:
			ev = pical.Component("VEVENT", r.tzdb)
			ev.properties = props
			r.children.append(ev)
	
	with open(ics_path, "wb") as w:
		for l in r.serialize():
			w.write(l.encode("UTF-8"))
			w.write("\r\n".encode("UTF-8"))


def ics_from_yaml(ics_path, tm=None):
	# ICS
	f = re.search(r"([^/]+).ics$", ics_path)
	assert f, yaml_path
	ics_grp = f.group(1)
	
	yaml_src = set()
	r = pical.parse(open(ics_path, "rb"))[0]
	for c in r.children:
		f = re.match("(\d{4})-(\d{2})-(\d{2})@(.+)", c["UID"])
		y,m,d,g = f.groups()
		yaml_src.add("docs/data/%s-%s-%s.yml" % (y,m,g))
	
	print(sorted(yaml_src))
	
	for yaml_path in yaml_src:
		yaml_to_ics(yaml_path, ics_path, tm)

