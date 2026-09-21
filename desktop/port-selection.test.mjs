import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("./main.cjs", import.meta.url), "utf8");
assert.match(source, /GarnetServer\.exe/, "桌面包应携带自己的任务队列运行时。");
assert.match(source, /startQueue\(\)/, "桌面启动器应启动随包任务队列运行时。");
const start = source.indexOf("function findFreePort");
const end = source.indexOf("function isPostgresReady", start);
const findFreePortSource = source.slice(start, end).trim();

test("findFreePort asks Windows for an OS-assigned port", async () => {
  const listenCalls = [];
  const net = {
    createServer() {
      let onError;
      return {
        once(event, handler) {
          assert.equal(event, "error");
          onError = handler;
        },
        listen(port, host, onListening) {
          listenCalls.push({ port, host });
          if (port !== 0) {
            onError(new Error("EACCES: system reserved port"));
            return;
          }
          onListening();
        },
        address() {
          return { port: 49152 };
        },
        close(callback) {
          callback?.();
        },
      };
    },
  };
  const findFreePort = vm.runInNewContext(`(${findFreePortSource})`, { net, Promise });

  assert.equal(await findFreePort(58080), 49152);
  assert.deepEqual(listenCalls, [{ port: 0, host: "127.0.0.1" }]);
});
