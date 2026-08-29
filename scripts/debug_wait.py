import traceback
import sys
sys.path.insert(0, r"D:\WorkBuddy\outputs\projects\2026-08-17-14-05-54\CAD-Knowledge-Base")
try:
    import scripts.wait_for_services as m
    print('module imported')
    sys.argv = ['wait', '--open']
    rc = m.main()
    print('rc', rc)
except Exception as e:
    traceback.print_exc()
