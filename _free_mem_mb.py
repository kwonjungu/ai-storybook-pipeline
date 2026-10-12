"""여유 물리 메모리(MB) 출력 — 배치 체인의 메모리 대기용."""
import ctypes as c


class M(c.Structure):
    _fields_ = [("l", c.c_ulong), ("p", c.c_ulong), ("t", c.c_ulonglong), ("a", c.c_ulonglong)] + \
               [("x%d" % i, c.c_ulonglong) for i in range(5)]


m = M(); m.l = c.sizeof(M)
c.windll.kernel32.GlobalMemoryStatusEx(c.byref(m))
print(m.a // 1048576)
