from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tools/tests'))
test=root/'tools/tests/test_gps_report_wire.py'
source=test.read_text(encoding='utf-8')
source=source.replace("else 'src/jt808.c'", "else 'build-cleanup-20260921/before/src/jt808.c'")
exec(compile(source,str(test),'exec'),{'__file__':str(test),'__name__':'__main__'})
