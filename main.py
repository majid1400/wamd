import sys
import json
import pyqrcode
import pika
import png
from io import BytesIO
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks
from twisted.internet.task import deferLater
from twisted.python.filepath import FilePath
from twisted.python.failure import Failure
from twisted.logger import (
    textFileLogObserver,
    FilteringLogObserver,
    LogLevelFilterPredicate,
    LogLevel,
    globalLogPublisher,
    Logger
)
from wamd.protocol import connectToWhatsAppServer, MultiDeviceWhatsAppClient
from wamd.common import AuthState
from wamd.messages import TextMessage
from config import Config

globalLogPublisher.addObserver(
    FilteringLogObserver(
        observer=textFileLogObserver(sys.stdout, timeFormat="%Y-%M-%d %H:%M:%S"),
        predicates=[LogLevelFilterPredicate(defaultLogLevel=LogLevel.levelWithName("debug"))]  # or info
    )
)

log = Logger()


def rabbit(msg):
    credentials = pika.PlainCredentials(Config.USER_RABBIT, Config.PASS_RABBIT)
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(Config.URL_RABBIT, 5672, Config.VIRTUAL_HOST_RABBIT, credentials))
    channel = connection.channel()
    channel.basic_publish(exchange='', routing_key=Config.ROUTING_KEY_RABBIT, body=json.dumps(msg))
    print(" [x] Sent {}".format(msg))
    connection.close()


def protocolFactory():
    authState = AuthState()
    sessionPath = FilePath("session.json")

    if sessionPath.exists():
        try:
            with open(sessionPath.path, "r") as f:
                session = json.loads(f.read())
                authState.populateFromJson(session)
        except:
            raise
    else:
        authState = None

    return MultiDeviceWhatsAppClient(authState)


def handleQr(qrInfo):
    log.info("QR Info: {qrInfo}", qrInfo=qrInfo)

    qrObj = pyqrcode.create(b",".join(qrInfo), error="L")
    qrIO = BytesIO()
    qrObj.png(qrIO, scale=6)
    qrBytes = qrIO.getvalue()
    qrIO.close()

    with open("qr.png", "wb") as qrFileIO:
        qrFileIO.write(qrBytes)


@inlineCallbacks
def extraMessage(connection, message):
    json = message._attrs
    print(json)
    rabbit(json)
    yield connection.sendReadReceipt(message)


def handleClose(connection, reason):
    sessionPath = FilePath("session.json")
    if reason.value.isLoggedOut:
        try:
            sessionPath.remove()
        except:
            pass
    else:
        with open(sessionPath.path, "w") as f:
            f.write(json.dumps(connection.authState.toJson(), indent=4))


@inlineCallbacks
def onConnect(connection):
    if not connection.authState.has("me"):
        connection.on("qr", handleQr)

    try:
        connection = yield connection.authenticate()
    except:
        pass
    else:
        connection.on("inbox", extraMessage)
        connection.on("close", handleClose)


connectToWhatsAppServer(
    protocolFactory=protocolFactory
).addCallback(
    onConnect
).addErrback(
    lambda f: log.failure("Connect Failure", failure=f)
)

reactor.run()
