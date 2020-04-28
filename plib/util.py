import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_email(sender,
               receiver,
               subject,
               body,
               host='localhost'):
    """ connect to an smtp host and ship email
    :param host: str of smtp host
    :param sender: email str
    :param receiver: email str
    :param body: str body
    """

    message = MIMEMultipart()
    message['Subject'] = subject
    message['From'] = sender
    message['To'] = receiver

    message.attach(MIMEText(body, "html"))
    msg = message.as_string()

    server = smtplib.SMTP(host, 25)
    try:
        server.sendmail(sender, receiver, msg)
    finally:
        server.quit()

def safeget(dct, keys):
    """ get sub items from a nested dict
    :param dct: nested dict
    :param keys: tuple of layers to unpack
    """
    for key in keys:
        try:
            dct = dct[key]
        except KeyError:
            return None
    return dct

def dedupe_list_of_dicts(l):
    """ unique a list of dicts
    :param l: list
    :return: list
    """
    return [i for n, i in enumerate(l) if i not in l[n + 1:]]
