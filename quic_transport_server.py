#!/usr/bin/env python3

# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
An example QuicTransport server based on the aioquic library.
Processes incoming streams and datagrams, and
replies with the ASCII-encoded length of the data sent in bytes.
Example use:
  python3 quic_transport_server.py certificate.pem certificate.key
Example use from JavaScript:
  let transport = new QuicTransport("quic-transport://localhost:4433/counter");
  await transport.ready;
  let stream = await transport.createBidirectionalStream();
  let encoder = new TextEncoder();
  let writer = stream.writable.getWriter();
  await writer.write(encoder.encode("Hello, world!"))
  writer.close();
  console.log(await new Response(stream.readable).text());
This will output "13" (the length of "Hello, world!") into the console.
"""

# ---- Dependencies ----
#
# This server only depends on Python standard library and aioquic.  See
# https://github.com/aiortc/aioquic for instructions on how to install
# aioquic.
#
# ---- Certificates ----
#
# QUIC always operates using TLS, meaning that running a QuicTransport server
# requires a valid TLS certificate.  The easiest way to do this is to get a
# certificate from a real publicly trusted CA like <https://letsencrypt.org/>.
# https://developers.google.com/web/fundamentals/security/encrypt-in-transit/enable-https
# contains a detailed explanation of how to achieve that.
#
# As an alternative, Chromium can be instructed to trust a self-signed
# certificate using command-line flags.  Here are step-by-step instructions on
# how to do that:
#
#   1. Generate a certificate and a private key:
# openssl req -newkey rsa:2048 -nodes -keyout certificate.key \
#           -x509 -out certificate.pem -subj '/CN=Test Certificate' \
#           -addext "subjectAltName = DNS:localhost"
#
#   2. Compute the fingerprint of the certificate:
# openssl x509 -pubkey -noout -in certificate.pem |
#           openssl rsa -pubin -outform der |
#           openssl dgst -sha256 -binary | base64
#      The result should be a base64-encoded blob that looks like this:
#          "Gi/HIwdiMcPZo2KBjnstF5kQdLI5bPrYJ8i3Vi6Ybck="
#
#   3. Pass a flag to Chromium indicating what host and port should be allowed
#      to use the self-signed certificate.  For instance, if the host is
#      localhost, and the port is 4433, the flag would be:
#         --origin-to-force-quic-on=localhost:4433
#
#   4. Pass a flag to Chromium indicating which certificate needs to be trusted.
#      For the example above, that flag would be:
#         --ignore-certificate-errors-spki-list=Gi/HIwdiMcPZo2KBjnstF5kQdLI5bPrYJ8i3Vi6Ybck=
#
# See https://www.chromium.org/developers/how-tos/run-chromium-with-flags for
# details on how to run Chromium with flags.

# open -a "Google Chrome" --args --origin-to-force-quic-on=localhost:4433 --ignore-certificate-errors-spki-list="ks9+B0hyVs6hwrZh3alG5XBKVGbAIrSnRWPSsdYXXFw="


import uuid
from aioquic.tls import SessionTicket
from aioquic.quic.events import (
    StreamDataReceived,
    StreamReset,
    DatagramFrameReceived,
    QuicEvent,
)
from aioquic.quic.connection import QuicConnection, END_STATES
from aioquic.quic.configuration import QuicConfiguration
from aioquic.asyncio import QuicConnectionProtocol, serve
from typing import Dict, Optional
from collections import defaultdict
import urllib.parse
import struct
import os
import io
import asyncio
import argparse
import sys


# Additional

BIND_ADDRESS = "::1"
BIND_PORT = 4433

connections_list = {}


def addConnections(new_connection, new_protocol) -> None:
    print(f"quic_transport_server addConnections{connections_list}")
    new_quic_transport_id = str(uuid.uuid4())
    # 入室情報を他の人に教えてあげる(streamで)
    for quic_transport_id, connection_dict in connections_list.items():
        response_id = connection_dict["connection"].get_next_available_stream_id(
            is_unidirectional=True
        )
        payload = str(f"joined={new_quic_transport_id}").encode("ascii")
        connection_dict["connection"].send_stream_data(response_id, payload, True)
        connection_dict["protocol"].transmit()

    connections_list[new_quic_transport_id] = {
        "connection": new_connection,
        "protocol": new_protocol,
    }
    # 自分のQuicTransportIDを教えてあげる(streamで)
    response_id = new_connection.get_next_available_stream_id(is_unidirectional=True)
    payload = str(f"quic_transport_id={new_quic_transport_id}").encode("ascii")
    new_connection.send_stream_data(response_id, payload, True)
    new_protocol.transmit()
    for quic_transport_id, connection_dict in connections_list.items():
        # if new_connection == connection_dict["connection"]:
        #     continue
        if new_quic_transport_id == quic_transport_id:
            continue
        response_id = new_connection.get_next_available_stream_id(
            is_unidirectional=True
        )
        payload = str(f"joined={quic_transport_id}").encode("ascii")
        new_connection.send_stream_data(response_id, payload, True)
        new_protocol.transmit()
    return new_quic_transport_id


def removeConnections(connection, protocol) -> None:
    connections_list.remove({"connection": connection, "protocol": protocol})
    print(
        f"quic_transport_server removeConnections removed :{connection},{protocol}, remain: {connections_list} "
    )
    # TODO:// 抜けたことを知らせる処理をかく


# QUIC uses two lowest bits of the stream ID to indicate whether the stream is:
#   (a) unidirectional or bidirectional,
#   (b) initiated by the client or by the server.
# See https://tools.ietf.org/html/draft-ietf-quic-transport-27#section-2.1 for
# more details.

# ストリームのIDをみると、タイプがわかる
# 0x0: クライアント開始&双方向
# 0x1: サーバー起動&双方向
# 0x2: クライアント開始&単方向
# 0x3: サーバー起動&単方向


def is_client_bidi_stream(stream_id):
    return stream_id % 4 == 0


# CounterHandler implements a really simple protocol:
#   - For every incoming bidirectional stream, it counts bytes it receives on
#     that stream until the stream is closed, and then replies with that byte
#     count on the same stream.
#   - For every incoming unidirectional stream, it counts bytes it receives on
#     that stream until the stream is closed, and then replies with that byte
#     count on a new unidirectional stream.
#   - For every incoming datagram, it sends a datagram with the length of
#     datagram that was just received.


class sendDataHandler:
    def __init__(self, protocol, connection) -> None:
        self.protocol = protocol
        self.connection = connection
        self.counters = defaultdict(str)
        self.quic_transport_id = addConnections(self.connection, self.protocol)

    def removeFromConnections(self) -> None:
        removeConnections(self.connection, self.proto)

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, DatagramFrameReceived):
            payload = event.data
            # self.connection.send_datagram_frame(payload)
            for quic_transport_id, connection_dict in connections_list.items():
                if self.quic_transport_id == quic_transport_id:
                    continue
                connection_dict["connection"].send_datagram_frame(payload)
                connection_dict["protocol"].transmit()


# QuicTransportProtocol handles the beginning of a QuicTransport connection: it
# parses the incoming URL, and routes the transport events to a relevant
# handler (in this example, CounterHandler).  It does that by waiting for a
# client indication (a special stream with protocol headers), and buffering all
# unrelated events until the client indication can be fully processed.


class QuicTransportProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.pending_events = []
        self.handler = None
        self.client_indication_data = b""

    # QuicConnectionProtocolクラスのtをオーバーライドしてる
    # quicを経由したデータ送信は全てここを通る？少なくともclient indicationはここを経由する

    def quic_event_received(self, event: QuicEvent) -> None:
        try:
            print(
                "quic_server_transport_server#QuicTransportProtocol#quic_event_received ============================================================================================================================================"
            )
            if self.is_closing_or_closed():
                self.handler.removeFromConnections()
                return
            # If the handler is available, that means the connection has been
            # established and the client  has been processed.
            if self.handler is not None:
                print(
                    "quic_server_transport_server#QuicTransportProtocol#quic_event_received handler is already available!!"
                )
                self.handler.quic_event_received(event)
                return
            # stream_id=2 => クライアントサイド開始&単方向
            if isinstance(event, StreamDataReceived) and event.stream_id == 2:
                # print(f'event.data : {event.data}')
                # print(f'event.end_stream : {event.end_stream}')
                self.client_indication_data += event.data
                # streamが終了している場合には開始する処理が走る。すでに開始している場合には何もせず？
                if event.end_stream:
                    # client_indicationを処理して、アクセスしてきたpathによって処理を変える。
                    # self.handlerにCounter handlerのようなものが入っていないといけない？
                    self.process_client_indication()
                    # print(self.is_closing_or_closed())
                    if self.is_closing_or_closed():
                        return
                    # Pass all buffered events into the handler now that it's
                    # available.
                    # print(self.pending_events)
                    for e in self.pending_events:
                        self.handler.quic_event_received(e)
                    self.pending_events.clear()
            else:
                # We have received some application data before we have the
                # request URL available, which is possible since there is no
                # ordering guarantee on data between different QUIC streams.
                # Buffer the data for now.
                self.pending_events.append(event)

        except Exception as e:
            print(e)
            self.handler = None
            self.close()
        # print('quic_event_received() ended')

    # Client indication follows a "key-length-value" format, where key and
    # length are 16-bit integers.  See
    # https://tools.ietf.org/html/draft-vvv-webtransport-quic-01#section-3.2

    def parse_client_indication(self, bs):
        while True:
            prefix = bs.read(4)
            if len(prefix) == 0:
                return  # End-of-stream reached.
            if len(prefix) != 4:
                raise Exception("Truncated key-length tag")
            # Cの構造体のデータとpython bytesオブジェクトの変換でstructは使用される
            key, length = struct.unpack("!HH", prefix)
            value = bs.read(length)
            if len(value) != length:
                raise Exception("Truncated value")
            yield (key, value)

    def process_client_indication(self) -> None:
        """
        ProtocolNegotiated/HandshakeCompletedのeventが送られてきた後に送られるClient_indicationを処理する。
        stream_idが2(クライアント開始・単方向)で、handlerがまだ渡されていない(開始していないstreamである)場合にこの関数が呼ばれる。
        (その時はend_stream=Trueで、self.is_closing_or_closed()がFalseになっているはず)
        new QuicTransport(url);の段階で、clientの情報が送られてくる。その情報はまず`quic_event_received()` で処理される
        """
        KEY_ORIGIN = 0
        KEY_PATH = 1
        indication = dict(
            self.parse_client_indication(io.BytesIO(self.client_indication_data))
        )

        origin = urllib.parse.urlparse(indication[KEY_ORIGIN].decode())
        path = urllib.parse.urlparse(indication[KEY_PATH]).decode()
        # Verify that the origin host is allowed to talk to this server.  This
        # is similar to the CORS (Cross-Origin Resource Sharing) mechanism in
        # HTTP.  See <https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS>.
        if origin.hostname != "localhost":
            raise Exception("Wrong origin specified")
        # Dispatch the incoming connection based on the path specified in the
        # URL.
        if path.path == "/mouse_point_share":
            self.handler = sendDataHandler(self, self._quic)
            print("handler attached!!!!!!!")
        else:
            raise Exception("Unknown path")

    def is_closing_or_closed(self) -> bool:
        return self._quic._close_pending or self._quic._state in END_STATES


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("certificate")
    parser.add_argument("key")
    args = parser.parse_args()
    # Quicのsetting
    configuration = QuicConfiguration(
        # Identifies the protocol used.  The origin trial uses the protocol
        # described in draft-vvv-webtransport-quic-01, hence the ALPN value.
        # See https://tools.ietf.org/html/draft-vvv-webtransport-quic-01#section-3.1
        alpn_protocols=["wq-vvv-01"],
        is_client=False,
        idle_timeout=300,
        # Note that this is just an upper limit; the real maximum datagram size
        # available depends on the MTU of the path.  See
        # <https://en.wikipedia.org/wiki/Maximum_transmission_unit>.
        max_datagram_frame_size=1500,
    )
    # Quicの鍵読み込み。
    configuration.load_cert_chain(args.certificate, args.key)

    loop = asyncio.get_event_loop()
    # 完了するまで続ける
    print("running quic server")
    loop.run_until_complete(
        serve(
            BIND_ADDRESS,
            BIND_PORT,
            configuration=configuration,
            create_protocol=QuicTransportProtocol,
        )
    )
    loop.run_forever()
