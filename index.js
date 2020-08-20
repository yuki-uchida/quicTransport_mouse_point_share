// "Connect" button handler.
async function prepareConnection() {
  let url = document.getElementById("url").value;
  var transport = new QuicTransport(url);
  // console.log(transport);
  console.log(`initializing QuicTransport Instance`);
  transport.closed
    .then(() => {
      console.log(`The QUIC connection to ${url} closed gracefully`);
    })
    .catch((error) => {
      console.error(`the QUIC connection to ${url} closed due to ${error}`);
    });
  await transport.ready;
  console.log("startReceivingDatagram");
  startReceivingDatagram(transport);
  console.log("startReceivingStream");
  startReceivingStream(transport);
  globalThis.currentTransport = transport;
  globalThis.streamNumber = 1;
  // console.log(transport);
}
async function startReceivingDatagram(transport) {
  const rs = transport.receiveDatagrams();
  const reader = rs.getReader();
  while (true) {
    const { value, done } = await reader.read();
    console.log(value);
    // console.log(value, Array.from(value), new TextDecoder("ascii").decode(value), done);
    if (done) {
      break;
    }
  }
}

async function startReceivingStream(transport) {
  let reader = transport.receiveStreams().getReader();
  while (true) {
    let result = await reader.read();
    if (result.done) {
      console.log("Done accepting unidirectional streams!");
      return;
    }
    let stream = result.value;
    let number = globalThis.streamNumber++;
    readDataFromStream(stream, number);
  }
}

async function readDataFromStream(stream, number) {
  let decoder = new TextDecoderStream("utf-8");
  let reader = stream.readable.pipeThrough(decoder).getReader();
  while (true) {
    let result = await reader.read();
    console.log(result);
    if (result.done) {
      console.log("Stream #" + number + " closed");
      return;
    }
    if (result.value.startsWith("quic_transport_id=")) {
      const index = result.value.indexOf("=");
      document.getElementById("QuicTransportID").value = result.value.slice(
        index + 1
      );
    } else if (result.value.startsWith("joined")) {
      const index = result.value.indexOf("=");
      document.getElementById("OtherQuicTransportID").value +=
        result.value.slice(index + 1) + "\n";
    }
  }
}

async function sendDatagram() {
  let QuicTransportID = document.getElementById("QuicTransportID").value;
  QuicTransportID = new TextEncoder().encode(QuicTransportID);
  const transport = globalThis.currentTransport;
  if (globalThis.writer) {
    writer.write(QuicTransportID);
  } else {
    const ws = transport.sendDatagrams();
    const writer = ws.getWriter();
    globalThis.writer = writer;
    writer.write(QuicTransportID);
    // console.log(QuicTransportID);
  }
}

async function sendStream() {
  const transport = globalThis.currentTransport;
  const stream = await transport.createSendStream();
  const writer = stream.writable.getWriter();
  const data1 = new Uint8Array([65, 66, 67]);
  writer.write(data1);
  try {
    await writer.close();
    console.log("All data has been sent.");
  } catch (error) {
    console.error(`An error occurred: ${error}`);
  }
}
