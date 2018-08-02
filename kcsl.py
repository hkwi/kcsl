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

NS1 = rdflib.Namespace("http://hkwi.github.io/kcsl/terms#")

_holidays = set()
def holidays():
	if not _holidays:
		fp = urlopen("http://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv")
		for r in csv.reader(io.TextIOWrapper(fp, encoding="CP932")):
			for c in r:
				m = re.match(r"(\d{4})-(\d+)-(\d+)", c)
				if m:
					_holidays.add(datetime.date(*[int(s) for s in m.groups()]))
	_holidays.add(datetime.date(2016, 11, 3))
	_holidays.add(datetime.date(2016, 11, 23))
	for i in range(22, 31):
		_holidays.add(datetime.date(2016, 12, i))
	for i in range(1, 11):
		_holidays.add(datetime.date(2017, 1, i))
	for i in range(22, 32):
		_holidays.add(datetime.date(2017, 3, i))
	for i in range(1, 17):
		_holidays.add(datetime.date(2017, 4, i))
	for i in range(21, 32):
		_holidays.add(datetime.date(2017, 7, i))
	for i in range(23, 31):
		_holidays.add(datetime.date(2017, 12, i))
	for i in range(1, 10):
		_holidays.add(datetime.date(2018, 1, i))
	for i in range(20, 31):
		_holidays.add(datetime.date(2018, 3, i))
	_holidays.add(datetime.date(2017, 9, 1))
	_holidays.add(datetime.date(2018, 2,12)) # 振替休日
	for i in range(1, 13):
		_holidays.add(datetime.date(2018, 4, i))
	_holidays.add(datetime.date(2018, 4, 30))
	for i in range(20, 32):
		_holidays.add(datetime.date(2018, 7, i))
	for i in range(1,5):
		_holidays.add(datetime.date(2018, 9, i))
	_holidays.add(datetime.date(2018, 9, 24))
	return _holidays

def main():
	base = "http://www.city.kobe.lg.jp/child/school/lunch/kyusyoku/kondate_shiyousyokuhin.html"
	r = lxml.html.parse(base).getroot()
	r.make_links_absolute()
	for anchor in r.xpath('//*[@id="contents"]//a'):
		href = anchor.get("href")
		if re.search(r"/\d+[^/]+$", href): # 献立表に違いない
			month = re.search("(\d+)月", list(anchor.xpath("preceding::h2/text()"))[-1]).group(1)
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
	
	if month <= found.month + 3:
		return found.year
	else:
		return found.year - 1

assert year_for(1, datetime.date(2017, 2, 1)) == 2017
assert year_for(2, datetime.date(2017, 2, 1)) == 2017
assert year_for(3, datetime.date(2017, 2, 1)) == 2017 # 
assert year_for(11, datetime.date(2016,11, 1)) == 2016
assert year_for(11, datetime.date(2016,12, 1)) == 2016
assert year_for(11, datetime.date(2017, 1, 1)) == 2016
assert year_for(6, datetime.date(2017, 7, 1)) == 2017
assert year_for(6, datetime.date(2017, 6, 1)) == 2017
assert year_for(6, datetime.date(2017, 5, 1)) == 2017

class PdfStore(object):
	def __init__(self, url, base=None):
		self.url = url
		
		m = re.match("(\d+)-(.*).pdf", os.path.basename(urlparse(url).path))
		assert m
		
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

def auto_csv(url, g, base=None):
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
		
		head = datetime.date(fs.year, fs.month, 1)
		
		days = []
		for i in range(31):
			o = head + datetime.timedelta(days=i)
			if o.year == head.year and o.month == head.month and o.weekday() < 5 and o not in holidays():
				days.append(o)
		
		# hand-crafted yaml
		if os.path.exists(fs.local("yml")):
			menus = yaml.load(open(fs.local("yml")))
		else:
			menus = auto_csv(url, g)
			print(yaml.dump(menus, allow_unicode=True))
			print(yaml.dump(menus, open(fs.local("yml"), "w"), allow_unicode=True))
			for m in menus:
				gmenus.update(set(m))
		
		assert len(days) == len(menus), "days=%d menus=%d" % (len(days), len(menus))
		
		grp = fs.group
		r = pical.parse(open("docs/%s.ics" % grp, "rb"))[0]
		for d,m in zip(days, menus):
			ev = None
			for c in r.children:
				if d == c["DTSTART"]:
					ev = c
			
			if ev is None:
				ev = pical.Component("VEVENT", r.tzdb)
				r.children.append(ev)
			
			ev.properties = []
			ev.properties.append(("UID", "%s@%s" % (d.isoformat(), grp), []))
			ev.properties.append(("DTSTAMP", tm, []))
			ev.properties.append(("DTSTART", d, [("VALUE",["DATE"])]))
			ev.properties.append(("SUMMARY", ",".join(m), []))
			ev.properties.append(("DESCRIPTION", "\n".join(m), []))
		
		with open("docs/%s.ics" % grp, "wb") as w:
			for l in r.serialize():
				w.write(l.encode("UTF-8"))
				w.write("\r\n".encode("UTF-8"))

if __name__ == "__main__":
	logging.basicConfig(level=logging.DEBUG)
	main()
	for m in sorted(gmenus):
		print(m)
