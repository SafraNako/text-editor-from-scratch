class CmdError(Exception):
    """A command that cannot be done (vim beeps, or shows a message): the message is shown and the pending command is forgotten."""


class Quit(Exception):
    pass
