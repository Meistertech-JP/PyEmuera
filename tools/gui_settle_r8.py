"""Pure timing policy for a missing/unchanging log, with no GUI operations.

Reference: received CaptureClose.ps1 initializes stableSince at window time;
raw run07 failure left the original process untouched. Windows integration
remains pending; callers must keep PID/HWND/execution identity checks.
"""
class LogSettle:
    def __init__(self,now):self.started=self.stable_since=now;self.last_size=None
    def observe(self,now,size=None):
        if size!=self.last_size:self.last_size=size;self.stable_since=now
        return now-self.started>=7 or now-self.started>=2.5 and now-self.stable_since>=1
