// Roda uma vez quando o servidor do Next sobe (next dev, next start e o server.js do build standalone).
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    // o Next repassa /api/* à API; daqui em diante cada requisição leva o IP real no X-Forwarded-For
    const { installForwardedFor } = await import("./lib/server/forwarded-for");
    installForwardedFor();
  }
}
