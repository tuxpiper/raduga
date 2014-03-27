from cloudcast.template import *
from cloudcast.library import stack_user

iSCMCompleteHandle = WaitConditionHandle()

iSCMComplete = WaitCondition(
	Handle = iSCMCompleteHandle,
	Timeout = "3600"		# Be generous with time
	)

iSCMData = Output(
	Description = "Output provided by the iSCM process",
	Value = iSCMComplete["Data"]
	)
