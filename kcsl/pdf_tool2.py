# encoding: utf-8
#
# You'll need:
# apt-get install libgs9
# pip install opencv-python camelot-py
#
import camelot
import unicodedata
import glob
import logging
import re

def de_kerning(c):
	# 行揃えが全幅になっているカラムで、文字数が少なすぎると、
	# 分割された文字として解析される。
	# ex:
	# | けい肉のみぞれあえ | => 「けい肉のみぞれあえ」
	# | ご      は      ん | => 「ご」「は」「ん」
	j = ""
	for t in c.split("\n"):
		if len(t)==1:
			j += t
		elif unicodedata.category(t[0])=="So" and re.match("^\s*.$", t[1:]):
			if j:
				yield j
			j = t
		else:
			if j:
				yield j
			j = ""
			yield t
	if j:
		yield j

def remove_space(t):
	yield re.sub("\s+", "", t)

def remove_interleaved_space(t):
	if re.match("^ *$", t[::2]):
		yield t[1::2]
	elif re.match("^ *$", t[1::2]):
		yield t[::2]
	else:
		yield t

def tok_by_knowledge1(t):
	m = re.match("^\s+([^\s]+)$", t[1:])
	if unicodedata.category(t[0])=="So" and m:
		yield t[0]+m.group(1)
	else:
		yield t

def tok_by_knowledge2(t):
	m = re.match(r"^(.*料理([\(（].*[）\)])?)", t)
	if "献立" in t:
		x = t.index("献立") + 2
		yield t[:x]
		yield t[x:]
	elif m:
		x = m.group(1)
		yield x
		yield t[len(x):]
	else:
		yield t

def tok_by_knowledge(t):
	if t == "パンバター":
		yield "パン"
		yield "バター"
	elif t == "ごはんぞうに田作り風":
		yield t[:3]
		yield t[3:6]
		yield t[6:]
	elif t == "ごはん焼鳥風にみそしる":
		yield t[:3]
		yield t[3:7]
		yield t[7:]
	elif t.startswith("ごはん焼鳥"):
		yield t[:3]
		yield t[3:5]
		yield t[5:]
	elif t.startswith("ごはん鉄火に"):
		yield t[:3]
		yield t[3:6]
		yield t[6:]
	elif t.startswith("ごはん他人とじ"):
		yield t[:3]
		yield t[3:7]
		yield t[7:]
	elif t.startswith("ごはんやまとに"):
		yield t[:3]
		yield t[3:7]
		yield t[7:]
	elif t.startswith("ごはん小"):
		yield t[:4]
		yield t[4:]
	elif t.startswith("ごはん(小)"):
		yield t[:6]
		yield t[6:]
	elif t.startswith("ごはん"):
		yield t[:3]
		yield t[3:]
	elif t == "パンコロッケ":
		yield t[:2]
		yield t[2:]
	elif t == "小型パン焼そば":
		yield t[:4]
		yield t[4:]
	elif t == "みそしるりんご":
		yield t[:4]
		yield t[4:]
	else:
		yield t

def remove_empty(t):
	if t:
		yield t

cell_tokenisers = [
	de_kerning,
	remove_space,
#	remove_interleaved_space,
#	tok_by_knowledge1,
	tok_by_knowledge2,
	tok_by_knowledge,
	remove_empty,
]

def shrink(s):
	rs = [
		["〇新", "料理"],
		["ごは", "ん（小）"],
	]
	for r in rs:
		o = []
		while len(s) >= len(r):
			if s[:len(r)] == r:
				o.append("".join(r))
				s = s[len(r):]
			else:
				o.append(s[0])
				s = s[1:]
		s = o + s
	
	return s

def cell_tok(cur, word):
	if cur < len(cell_tokenisers):
		for c in cell_tokenisers[cur](word):
			for t in cell_tok(cur+1, c):
				yield t
	else:
		yield word

def pdf_tok(filename):
	x = camelot.read_pdf(filename)
	assert len(x) == 1
	# 実データ解析結果での行数は安定しなかったので、
	# 行番号の抽出が必要
	df = x[0].df
	
	def kondate_index():
		for k in range(df.shape[1]):
			menu = df[df[k].str.contains(r'こんだて')]
			if len(menu) == 2:
				return k, menu
		return 0, None
	
	dt = df.T
	o = [ k for k in range(dt.shape[1])
		if len(dt[dt[k].str.contains(r'冷凍')]) > 2 ]
	
	k, menu = kondate_index()
	assert len(menu)==2, "%s %s" % (filename, menu)
	
	ret = []
	crow = None
	for i,r in df.iterrows():
		if i in menu.index:
			if crow:
				ret += [c for c in crow if c]
			crow = []
		
		if i in o:
			if crow:
				ret += [c for c in crow if c]
			crow = None
		
		rseq = []
		if crow is not None:
			for j,c in r.items():
				if j>k:
					if len(c):
						tok = [t for t in cell_tok(0, c)]
					else:
						tok = []
					
					tok = shrink(tok)
					rseq.append(tok)
		
#		print("RSEQ", rseq)
		
		if crow:
			assert len(crow)==len(rseq), repr([crow, rseq])
			crow = [a+b for a,b in zip(crow, rseq)]
		elif crow is not None:
			crow = rseq
		
#		print("CROW", i, crow)
	
	if crow:
		ret += [c for c in crow if c]
#					yield (i, j, t)
#					print(filename, i, j, t)
	return ret

if __name__=="__main__":
	for f in glob.glob("*.pdf"):
		for i, j, t in pdf_tok(f):
			print(f, i, j, t)
