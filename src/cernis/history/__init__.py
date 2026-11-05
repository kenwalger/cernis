"""History: comparing stored runs, and classifying what changed (DESIGN.md section 5).

Pure functions over stored records; nothing here fetches. Import the
submodules directly: :mod:`cernis.history.fields` (who controls each head
field), :mod:`cernis.history.classify` (page and finding changes), and
:mod:`cernis.history.report` (the ``cernis diff`` output). This package has no
imports of its own, so the store can use :mod:`cernis.history.fields` without
a cycle.
"""
