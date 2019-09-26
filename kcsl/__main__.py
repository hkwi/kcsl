import argparse
import logging
from . import entr

if __name__ == "__main__":
	ap = argparse.ArgumentParser()
	ap.add_argument("icss", nargs="*")
	argv = ap.parse_args()
	
	logging.basicConfig(level=logging.INFO)
	sup = logging.getLogger("pdfminer")
	sup.setLevel(logging.ERROR)
	if argv.icss:
		# ics_from_yaml(ics_path, yaml_path, tm=None)
		for ics in argv.icss:
			entr.ics_from_yaml(ics)
	else:
		entr.main()
	
	for m in sorted(entr.gmenus):
		print(m)
