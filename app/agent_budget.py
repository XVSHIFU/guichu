"""Shared provider validation and runtime budgets."""
DEFAULTS = dict(max_output_tokens=4096, timeout=120, max_tool_calls=16, max_requests=6)
LIMITS = dict(max_output_tokens=(1,32768), timeout=(1,300), max_tool_calls=(0,32), max_requests=(1,12))
def effective(config):
    result={}
    for key,(low,high) in LIMITS.items():
        value=config.get(key,DEFAULTS[key])
        if type(value) is not int: value=DEFAULTS[key]
        result[key]=max(low,min(high,value))
    return result
