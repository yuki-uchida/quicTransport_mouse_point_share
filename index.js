// "Connect" button handler.
async function prepareConnection() {
  let url = document.getElementById("url").value;
  var transport = new WebTransport(url);
  console.log(`initializing WebTransport Instance`);
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
}
let prev_mouse_point_x = null;
let prev_mouse_point_y = null;

async function startReceivingDatagram(transport) {
  const reader = transport.datagramReadable.getReader();
  while (true) {
    const { value, done } = await reader.read();
    let result = new TextDecoder("ascii").decode(value);
    // result = "mouse_point=x,y"
    if (result.startsWith("mouse_point=")) {
      const index = result.indexOf("=");
      const [mouse_point_x, mouse_point_y] = result.slice(index + 1).split(",");
      const myPics = document.getElementById("myPics");
      const context = myPics.getContext("2d");
      if (prev_mouse_point_x && prev_mouse_point_y) {
        drawLine(
          context,
          prev_mouse_point_x,
          prev_mouse_point_y,
          mouse_point_x,
          mouse_point_y
        );
      }
      prev_mouse_point_x = mouse_point_x;
      prev_mouse_point_y = mouse_point_y;
    }
    if (done) {
      break;
    }
  }
}

async function startReceivingStream(transport) {
  let reader = transport.incomingUnidirectionalStreams.getReader();
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

async function sendMousePointDatagram() {
  let QuicTransportID = document.getElementById("QuicTransportID").value;
  QuicTransportID = new TextEncoder().encode(QuicTransportID);
  const transport = globalThis.currentTransport;
  mouse_point_share();
}
let isDrawing = false;
function drawLine(context, x1, y1, x2, y2) {
  context.beginPath();
  context.strokeStyle = "black";
  context.lineWidth = 1;
  context.moveTo(x1, y1);
  context.lineTo(x2, y2);
  context.stroke();
  context.closePath();
}

var timeoutId;
function mouse_point_share() {
  const myPics = document.getElementById("myPics");
  const context = myPics.getContext("2d");
  myPics.addEventListener("mousedown", (e) => {
    x = e.offsetX;
    y = e.offsetY;
    isDrawing = true;
  });

  myPics.addEventListener("mousemove", (e) => {
    if (timeoutId) return;
    // Prevent from very high frequency sending.
    timeoutId = setTimeout(function () {
      timeoutId = 0;

      if (isDrawing === true) {
        drawLine(context, x, y, e.offsetX, e.offsetY);
        x = e.offsetX;
        y = e.offsetY;
        const text = `mouse_point=${e.offsetX},${e.offsetY}`;
        const encoded_text = new TextEncoder().encode(text);

        if (globalThis.writer) {
          writer.write(encoded_text);
        } else {
          const ws = globalThis.currentTransport.datagramWritable;
          const writer = ws.getWriter();
          globalThis.writer = writer;
          writer.write(encoded_text);
        }
      }
    }, 10);
  });

  window.addEventListener("mouseup", (e) => {
    if (isDrawing === true) {
      drawLine(context, x, y, e.offsetX, e.offsetY);
      x = 0;
      y = 0;
      isDrawing = false;
    }
  });
}
