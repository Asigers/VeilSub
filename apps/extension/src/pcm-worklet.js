class Pcm16Processor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = [];
    this.frameSize = 1600;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;

    for (let i = 0; i < input.length; i += 1) {
      const sample = Math.max(-1, Math.min(1, input[i]));
      this.buffer.push(sample < 0 ? sample * 0x8000 : sample * 0x7fff);
    }

    while (this.buffer.length >= this.frameSize) {
      const frame = new Int16Array(this.buffer.splice(0, this.frameSize));
      this.port.postMessage(frame.buffer, [frame.buffer]);
    }
    return true;
  }
}

registerProcessor('veilsub-pcm16', Pcm16Processor);
