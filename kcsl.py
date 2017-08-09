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
	_holidays.add(datetime.date(2017, 9, 1))
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
		m = re.match("(\d+)-(.*).pdf", os.path.basename(self.local))
		if m:
			month, self.group = m.groups()
			self.month = int(month)
	
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

def auto_csv(url, g):
	out = Fs(re.sub("\.pdf$", ".csv", url))
	if not os.path.exists(out.local):
		with open(out.local, "w", encoding="UTF-8") as w:
			csv.writer(w).writerows(
				pte.table_to_list(
					pte.process_page(Fs(url).local, "1", whitespace="raw", pad=1), 1)[1])
	
	g.set((rdflib.URIRef(url), NS1["csv"], rdflib.URIRef(out.remote)))
	
	rs = [r for r in csv.reader(open(out.local, encoding="UTF-8"))]
	menus = []
	slot = None
	mask = None
	skip_in_cell = 0
	for i,r in enumerate(rs):
		for j,c in enumerate(r):
			c = c.encode("CP932", "ignore").decode("CP932", "ignore")
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
				elif Fs(url).month == datetime.date(2016,12,1):
					if "地区１２月１４日" in content:
						mask.add(j)
					elif "\u202c" in content:
						mask.add(j)
				
				if "とんじゃ" in content:
					print(content)
				
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
	
	menus = [m for m in menus if not re.match(r"^[\(\)（）]+$", "".join(m))]
	print(yaml.dump(menus, allow_unicode=True))
	return menus

gmenus = set()

def proc(url, **kwargs):
	rec = "docs/record.ttl"
	download(url, history=rec)
	with _history(rec) as g:
		target = Fs(url)
		tm_g = g.value(rdflib.URIRef(url), NS1["last-modified"])
		if tm_g:
			tm = datetime.datetime(*parsedate(tm_g.value)[:6])
		
		if target.month + 6 < tm.month:
			head = datetime.date(tm.year+1, target.month, 1)
		else:
			head = datetime.date(tm.year, target.month, 1)
#		out = Fs(re.sub("\.pdf$", "_man.yml", url))
#		if not os.path.exists(out.local):
		
		days = []
		for i in range(31):
			o = head + datetime.timedelta(days=i)
			if o.year == head.year and o.month == head.month and o.weekday() < 5 and o not in holidays():
				days.append(o)
		
		yout = Fs(re.sub("\.pdf$", ".yml", url))
		# hand-crafted yaml
		if os.path.exists(yout.local):
			menus = yaml.load(open(yout.local))
			assert len(days) == len(menus), "days=%d menus=%d" % (len(days), len(menus))
		else:
			menus = auto_csv(url, g)
			assert len(days) == len(menus), "days=%d menus=%d" % (len(days), len(menus))
			print(yaml.dump(menus, open(yout.local, "w"), allow_unicode=True))
			for m in menus:
				gmenus.update(set(m))
			print(yaml.dump(menus, allow_unicode=True))
		
		grp = target.group
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
