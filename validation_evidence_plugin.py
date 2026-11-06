"""Read-only Arelle telemetry; never suppresses or changes validation results.

Arelle 2.45 stores formula result dictionaries in model.errors even when every
assertion succeeds. Its CLI consequently returns 3 for some valid reports.
Record those dictionaries separately from real errors so the adapter need not
guess from exit status or silently discard formula results.
"""
import json


def summarize(errors):
    assertions = {}
    error_codes = []
    for error in errors:
        if isinstance(error, dict):
            for name, counts in error.items():
                if (not isinstance(counts, (tuple, list)) or len(counts) != 5
                        or any(type(c) is not int or c < 0 for c in counts)):
                    error_codes.append("UNRECOGNIZED_ASSERTION_RESULT")
                else:
                    assertions[str(name)] = list(counts)
                    if counts[1] or counts[4]:
                        error_codes.append("UNSATISFIED_ASSERTION:" + str(name))
        else:
            error_codes.append(str(error))
    return {"assertions": assertions, "errors": error_codes}


def capture(cntlr, options, modelXbrl, *args, **kwargs):
    data = summarize(modelXbrl.errors)
    data["controller_errors"] = [str(e) for e in cntlr.errors]
    cntlr.addToLog(json.dumps(data, sort_keys=True), messageCode="KVK.validationEvidence")


__pluginInfo__ = {
    "name": "KVK validation evidence", "version": "1.0", "description": "Read-only assertion and engine evidence",
    "license": "Apache-2", "author": "KVK preparation application",
    "CntlrCmdLine.Xbrl.Run": capture,
}
