import http from "node:http";
import type { AddressInfo } from "node:net";
import { describe, expect, it } from "vitest";
import { appendForwardedFor, installForwardedFor } from "./forwarded-for";

describe("appendForwardedFor", () => {
  it("acrescenta o endereço do socket à direita, sem apagar o que veio", () => {
    expect(appendForwardedFor(undefined, "::1")).toBe("::1");
    expect(appendForwardedFor("6.6.6.6", "198.51.100.7")).toBe("6.6.6.6, 198.51.100.7");
    expect(appendForwardedFor(["6.6.6.6", "7.7.7.7"], "198.51.100.7")).toBe("6.6.6.6, 7.7.7.7, 198.51.100.7");
  });

  it("sem endereço do socket, deixa um marcador inválido (a API usa o IP do próprio Next)", () => {
    expect(appendForwardedFor("6.6.6.6", undefined)).toBe("6.6.6.6, unknown");
  });
});

describe("installForwardedFor", () => {
  it("o servidor HTTP vê o X-Forwarded-For já com o endereço real", async () => {
    installForwardedFor();
    installForwardedFor(); // idempotente: não acrescenta duas vezes
    const server = http.createServer((req, res) => res.end(String(req.headers["x-forwarded-for"])));
    await new Promise<void>((ok) => server.listen(0, "127.0.0.1", ok));
    const { port } = server.address() as AddressInfo;
    try {
      const got = await new Promise<string>((ok, fail) => {
        http
          .get({ host: "127.0.0.1", port, headers: { "X-Forwarded-For": "6.6.6.6" } }, (res) => {
            let body = "";
            res.on("data", (c) => (body += c));
            res.on("end", () => ok(body));
          })
          .on("error", fail);
      });
      expect(got).toBe("6.6.6.6, 127.0.0.1");
    } finally {
      server.close();
    }
  });
});
