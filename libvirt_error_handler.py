
import logging
import libvirt

def libvirt_error_handler(conn, error):
    """
    Custom libvirt error handler that logs errors to the logging framework.
    """
    if error[3] == libvirt.VIR_ERR_ERROR:
        level = logging.ERROR
    elif error[3] == libvirt.VIR_ERR_WARNING:
        level = logging.WARNING
    else:
        level = logging.INFO

    logging.log(
        level,
        "libvirt error: code=%d, domain=%d, message='%s', level=%d, conn='%s'",
        error[0],
        error[1],
        error[2],
        error[3],
        error[4],
    )

def register_error_handler():
    """
    Registers the custom libvirt error handler.
    """
    libvirt.registerErrorHandler(f=libvirt_error_handler, ctx=None)
