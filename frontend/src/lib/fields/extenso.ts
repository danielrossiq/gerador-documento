// Espelho de backend/app/modules/fields/extenso.py — valores em reais por extenso (pt-BR).
// shared/field-vectors.json roda nas duas suítes para impedir divergência.

const UNITS = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze", "treze", "catorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"];
const TENS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"];
const HUNDREDS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos", "oitocentos", "novecentos"];
const SCALES: [string, string][] = [["mil", "mil"], ["milhão", "milhões"], ["bilhão", "bilhões"], ["trilhão", "trilhões"]];
export const MAX_INTEGER = 10n ** 15n - 1n; // até 999 trilhões

function belowThousand(n: number): string {
  if (n === 100) return "cem";
  const parts: string[] = [];
  const h = Math.floor(n / 100);
  const rest = n % 100;
  if (h) parts.push(HUNDREDS[h]);
  if (rest) {
    if (rest < 20) parts.push(UNITS[rest]);
    else {
      const t = Math.floor(rest / 10);
      const u = rest % 10;
      parts.push(TENS[t] + (u ? ` e ${UNITS[u]}` : ""));
    }
  }
  return parts.join(" e ");
}

/** 0 ≤ n ≤ MAX_INTEGER → texto por extenso (masculino). */
export function integerWords(n: bigint): string {
  if (n < 0n || n > MAX_INTEGER) throw new RangeError("número fora do intervalo do extenso");
  if (n === 0n) return "zero";
  const groups: number[] = [];
  while (n > 0n) {
    groups.push(Number(n % 1000n));
    n /= 1000n;
  }
  const words: [number, string][] = [];
  for (let i = groups.length - 1; i >= 0; i--) {
    const g = groups[i];
    if (!g) continue;
    if (i === 0) words.push([g, belowThousand(g)]);
    else if (i === 1) words.push([g, g === 1 ? "mil" : `${belowThousand(g)} mil`]);
    else {
      const [sing, plur] = SCALES[i - 1];
      words.push([g, `${belowThousand(g)} ${g === 1 ? sing : plur}`]);
    }
  }
  let out = words[0][1];
  for (let idx = 1; idx < words.length; idx++) {
    const [g, text] = words[idx];
    const last = idx === words.length - 1;
    out += (last && (g < 100 || g % 100 === 0) ? " e " : " ") + text;
  }
  return out;
}

/** Valor canônico ("1500.00") → "mil e quinhentos reais"; null se não for um decimal canônico no intervalo. */
export function currencyWords(canonical: string): string | null {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(canonical);
  if (!m) return null;
  // arredonda para centavos (meio para cima, como o ROUND_HALF_UP do servidor)
  const frac = (m[3] ?? "").padEnd(3, "0");
  let cents = BigInt(m[2]) * 100n + BigInt(frac.slice(0, 2));
  if (Number(frac[2]) >= 5) cents += 1n;
  const negative = m[1] === "-" && cents > 0n;
  const reais = cents / 100n;
  const centavos = Number(cents % 100n);
  if (reais > MAX_INTEGER) return null;
  const parts: string[] = [];
  if (reais > 0n || !centavos) {
    const de = reais >= 1_000_000n && reais % 1_000_000n === 0n;
    parts.push(`${integerWords(reais)} ${de ? "de " : ""}${reais === 1n ? "real" : "reais"}`);
  }
  if (centavos) parts.push(`${integerWords(BigInt(centavos))} ${centavos === 1 ? "centavo" : "centavos"}`);
  return (negative ? "menos " : "") + parts.join(" e ");
}
