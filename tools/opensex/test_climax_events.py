"""climax_events.py reads OStimClimax's time and nothing else's (docs/design/climax-and-stimulation.md §4.2)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from climax_events import climax_at  # noqa: E402

ROW = '<hkparam name="time">%s</hkparam>\n  <hkparam name="text">%s</hkparam>'


def main():
    checks = [
        (climax_at(ROW % ("1.000000", "OStimClimax")) == 1.0, "the annotation's time"),
        (climax_at(ROW % ("0.5", "OStimEvent") + ROW % ("2.25", "OStimClimax")) == 2.25, "past another annotation"),
        (climax_at(ROW % ("0.5", "OStimEvent")) is None, "no annotation, no time"),
    ]
    bad = [what for ok, what in checks if not ok]
    for what in bad:
        print("FAIL", what)
    print("test_climax_events: %s" % ("ok" if not bad else "%d failed" % len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
