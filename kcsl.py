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
				m = re.match(r"(\d{4})/(\d+)/(\d+)", c)
				if m:
					_holidays.add(datetime.date(*[int(s) for s in m.groups()]))
	for i in range(22, 31):
		_holidays.add(datetime.date(2016, 12, i))
	for i in range(1, 11):
		_holidays.add(datetime.date(2017, 1, i))
	
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

class Fs(object):
	def __init__(self, url):
		self.url = url
	
	@property
	def path(self):
		pc = urlparse(self.url)
		return pc.netloc + pc.path
	
	@property
	def local(self):
		return "docs/" + self.path
	
	@property
	def remote(self):
		return "http://hkwi.github.com/kcsl/" + self.path

def download(url, history=None):
	fs = Fs(url)
	with _history(history) as g:
		lm = g.value(rdflib.URIRef(url), NS1["last-modified"])
		
		fp = None
		if os.path.exists(fs.local) and lm:
			fp = requests.get(url, headers={"If-Modified-Since":lm})
			if fp.status_code == 304: # xxx: not modified
				return
		
		if fp is None:
			fp = requests.get(url)
		
		if not fp.ok:
			return
		
		logging.info("downloading %s" % url)
		os.makedirs(os.path.dirname(fs.local), exist_ok=True)
		with open(fs.local, "wb") as w:
			for data in fp:
				w.write(data)
		
		g.set((rdflib.URIRef(url), NS1["mirror"], rdflib.URIRef(fs.remote)))
		lm = fp.headers.get("last-modified")
		if lm:
			g.set((rdflib.URIRef(url), NS1["last-modified"], rdflib.Literal(lm)))

def proc(url, **kwargs):
	rec = "docs/record.ttl"
	download(url, history=rec)
	with _history(rec) as g:
		tm = g.value(rdflib.URIRef(url), NS1["last-modified"])
		if tm:
			tm = datetime.datetime(*parsedate(tm.value)[:6])
		
		assert tm
		
		out = Fs(re.sub("\.pdf$", ".csv", url))
		if not os.path.exists(out.local):
			with open(out.local, "w", encoding="UTF-8") as w:
				csv.writer(w).writerows(
					pte.table_to_list(
						pte.process_page(Fs(url).local, "1", whitespace="raw", pad=1), 1)[1])
		
		g.set((rdflib.URIRef(url), NS1["csv"], rdflib.URIRef(out.remote)))
		
		month,grp = re.match("(\d+)-(.*).pdf", os.path.basename(Fs(url).local)).groups()
		
		n = datetime.datetime.now()
		if tm:
			n = tm
		
		if int(month) + 6 < n.month:
			s = datetime.date(n.year+1, int(month), 1)
		else:
			s = datetime.date(n.year, int(month), 1)
		
		days = []
		for i in range(31):
			o = s + datetime.timedelta(days=i)
			if e and o >= e:
				break
			
			if o.year == s.year and o.month == s.month and o.weekday() < 5 and o not in holidays():
				days.append(o)
		
		rs = [r for r in csv.reader(open(out.local, encoding="UTF-8"))]
		menus = []
		slot = None
		mask = None
		skip_in_cell = 0
		for i,r in enumerate(rs):
			for j,c in enumerate(r):
				if c.strip().startswith("こんだて") or "\nこんだて" in c:
					if slot:
						menus += [slot[k] for k in sorted(slot.keys()) if k not in mask]
					slot = {}
					mask = set()
					skip_in_cell = 0
					if not c.strip().startswith("こんだて"):
						for cr in c.split("\n"):
							skip_in_cell += 1
							if cr.startswith("こんだて"):
								break
				elif re.sub("[\s　]", "", c).strip().startswith("おかず"):
					if slot:
						menus += [slot[k] for k in sorted(slot.keys()) if k not in mask]
					slot = None
				elif slot is not None:
					content = re.sub("[\s　]", "", c)
					if "エネルギー" in content:
						mask.add(j)
					elif "お知らせ" in content:
						mask.add(j)
					elif s == datetime.date(2016,12,1):
						if "地区１２月１４日" in content:
							mask.add(j)
						elif "\u202c" in content:
							mask.add(j)
					
					if content:
						ts = [re.sub("[\s　]","",u).strip() for u in c.split("\n")]
						if skip_in_cell:
							ts = ts[skip_in_cell:]
						
						if j in slot:
							slot[j] += [t for t in ts if t]
						else:
							slot[j] = [t for t in ts if t]
		if slot:
			menus += [slot[k] for k in sorted(slot.keys()) if k not in mask]
		
		assert len(days) == len(menus), "days=%d menus=%d" % (len(days), len(menus))
		
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
