// Documentos de exemplo da demonstração da landing (dados fictícios; CPFs válidos de teste).
// Cada parágrafo é uma lista de trechos: texto fixo ou referência a um campo ({ f }). `as: "words"` mostra o
// valor por extenso (moeda) ou a data escrita ("21 de outubro de 2026") — o mesmo que o produto faz no documento.

export type DemoFieldType = "text" | "cpf" | "currency" | "date" | "oab" | "number";

export type DemoField = {
  key: string;
  label: string;
  type: DemoFieldType;
  /** valor encontrado no documento original */
  example: string;
  /** valor que a demonstração automática digita (outro cliente) */
  alt?: string;
};

export type Segment = string | { f: string; as?: "words" };

export type DemoDoc = {
  id: string;
  tab: string;
  title: string;
  /** padrão do nome do arquivo gerado */
  file: (v: Record<string, string>) => string;
  fields: DemoField[];
  body: Segment[][];
  signature?: Segment[];
};

const slug = (s: string) =>
  s
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 40) || "documento";

export const DEMO_DOCS: DemoDoc[] = [
  {
    id: "honorarios",
    tab: "Contrato de honorários",
    title: "CONTRATO DE HONORÁRIOS ADVOCATÍCIOS",
    file: (v) => `honorarios-${slug(v.cliente)}.pdf`,
    fields: [
      { key: "cliente", label: "Nome do cliente", type: "text", example: "Maria Aparecida Souza", alt: "João Pedro Lima" },
      { key: "cpf", label: "CPF do cliente", type: "cpf", example: "529.982.247-25", alt: "111.444.777-35" },
      { key: "advogado", label: "Advogado(a)", type: "text", example: "Dr. Paulo Mendes" },
      { key: "oab", label: "OAB", type: "oab", example: "OAB/MG 123.456" },
      { key: "objeto", label: "Objeto", type: "text", example: "ação de revisão contratual" },
      { key: "valor", label: "Valor dos honorários", type: "currency", example: "4.500,00", alt: "7.800,00" },
      { key: "parcelas", label: "Parcelas", type: "number", example: "3" },
      { key: "vencimento", label: "1º vencimento", type: "date", example: "10/11/2026" },
      { key: "data", label: "Data de assinatura", type: "date", example: "21/10/2026" },
    ],
    body: [
      [
        "Pelo presente instrumento particular, ",
        { f: "cliente" },
        ", inscrita no CPF sob o nº ",
        { f: "cpf" },
        ", doravante CONTRATANTE, contrata ",
        { f: "advogado" },
        ", inscrito na ",
        { f: "oab" },
        ", para patrocinar ",
        { f: "objeto" },
        ".",
      ],
      [
        "Pelos serviços, a CONTRATANTE pagará o valor de ",
        { f: "valor" },
        " (",
        { f: "valor", as: "words" },
        "), em ",
        { f: "parcelas" },
        " parcelas mensais, vencendo a primeira em ",
        { f: "vencimento" },
        ".",
      ],
      ["Os honorários de êxito, se houver, serão tratados em aditivo próprio, assinado pelas partes."],
      ["Belo Horizonte, ", { f: "data", as: "words" }, "."],
    ],
    signature: [{ f: "cliente" }, " — CONTRATANTE"],
  },
  {
    id: "procuracao",
    tab: "Procuração",
    title: "PROCURAÇÃO AD JUDICIA",
    file: (v) => `procuracao-${slug(v.outorgante)}.pdf`,
    fields: [
      { key: "outorgante", label: "Outorgante", type: "text", example: "Carlos Eduardo Ramos", alt: "Ana Beatriz Costa" },
      { key: "profissao", label: "Profissão", type: "text", example: "engenheiro civil" },
      { key: "cpf", label: "CPF do outorgante", type: "cpf", example: "111.444.777-35", alt: "529.982.247-25" },
      { key: "endereco", label: "Endereço", type: "text", example: "Av. Paulista, 1.000, São Paulo/SP" },
      { key: "advogado", label: "Advogado(a)", type: "text", example: "Dra. Juliana Teixeira" },
      { key: "oab", label: "OAB", type: "oab", example: "OAB/SP 98.765" },
      { key: "acao", label: "Ação", type: "text", example: "ação de indenização por danos morais" },
      { key: "parte", label: "Parte contrária", type: "text", example: "Construtora Alfa Ltda." },
      { key: "data", label: "Data", type: "date", example: "21/10/2026" },
    ],
    body: [
      [
        "OUTORGANTE: ",
        { f: "outorgante" },
        ", brasileiro, ",
        { f: "profissao" },
        ", inscrito no CPF sob o nº ",
        { f: "cpf" },
        ", residente em ",
        { f: "endereco" },
        ".",
      ],
      ["OUTORGADA: ", { f: "advogado" }, ", advogada inscrita na ", { f: "oab" }, "."],
      [
        "PODERES: os da cláusula ad judicia et extra, para propor e acompanhar ",
        { f: "acao" },
        " contra ",
        { f: "parte" },
        ", podendo transigir, desistir, receber e dar quitação.",
      ],
      ["São Paulo, ", { f: "data", as: "words" }, "."],
    ],
    signature: [{ f: "outorgante" }],
  },
  {
    id: "recibo",
    tab: "Recibo de aluguel",
    title: "RECIBO DE ALUGUEL",
    file: (v) => `recibo-${slug(v.locatario)}.pdf`,
    fields: [
      { key: "locatario", label: "Locatário(a)", type: "text", example: "Fernanda Oliveira", alt: "Ricardo Alves" },
      { key: "cpf", label: "CPF do locatário", type: "cpf", example: "390.533.447-05", alt: "111.444.777-35" },
      { key: "valor", label: "Valor do aluguel", type: "currency", example: "2.350,00", alt: "3.100,00" },
      { key: "mes", label: "Mês de referência", type: "text", example: "outubro de 2026" },
      { key: "imovel", label: "Endereço do imóvel", type: "text", example: "Rua Bahia, 45, ap. 302, Curitiba/PR" },
      { key: "data", label: "Data do pagamento", type: "date", example: "05/10/2026" },
      { key: "locador", label: "Locador", type: "text", example: "Imobiliária Horizonte" },
    ],
    body: [
      [
        "Recebi de ",
        { f: "locatario" },
        ", inscrita no CPF sob o nº ",
        { f: "cpf" },
        ", a importância de ",
        { f: "valor" },
        " (",
        { f: "valor", as: "words" },
        "), referente ao aluguel do mês de ",
        { f: "mes" },
        " do imóvel situado em ",
        { f: "imovel" },
        ".",
      ],
      ["Para maior clareza, firmo o presente recibo, dando plena quitação do valor acima."],
      ["Curitiba, ", { f: "data", as: "words" }, "."],
    ],
    signature: [{ f: "locador" }, " — LOCADOR"],
  },
];

export const initialValues = (doc: DemoDoc): Record<string, string> =>
  Object.fromEntries(doc.fields.map((f) => [f.key, f.example]));
