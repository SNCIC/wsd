from . import test_fai
from . import test_fai_matrix
# DISABLED 2026-10-29 report-daily-workbench: the FAI report-mode
# collector is disabled, so its whole test file is too
# (restore: wsd-doc/openspec/changes/report-daily-workbench/design.md sec.5)
# from . import test_fai_report
from . import test_fai_timing
from . import test_ipqc_patrol
from . import test_matrix_regression
from . import test_oqc_entry
from . import test_sampling_stats
from . import test_batch_pass_fai
from . import test_iqc_arrival_batch
from . import test_pass_ng_no_auto_issue
from . import test_report_link_disabled
from . import test_oqc_disposition
