export type AssistantOperation = "template" | "extract" | "review" | "command" | "batch-clean";
export type AssistantField = {name:string;label:string;type:string;value?:string|null};
export type AssistantRow = Record<string,string|number|boolean|null>;
export type AssistantRequest = {text?:string;command?:string;fields?:AssistantField[];rows?:AssistantRow[]};
export type AssistantResponse = {operation:AssistantOperation;mode:"demo"|"live";result:{text:string;fields:AssistantField[];issues:{severity:"info"|"warning";message:string}[];actions:{type:"preview";description:string}[];rows:AssistantRow[]};warnings:string[];applied:false};
export type BillingUsage = {provider:"none";plan:{id:string;name:string;checkout_enabled:false};mode:"demo"|"live";usage:{requests?:number;tokens_reserved?:number;cost_reserved_microusd?:number;available:boolean;period:string;scope:string};limits:{requests_per_day:number;tokens_per_day:number;cost_microusd_per_day:number;max_output_tokens:number};billing_enabled:false};
/** Limites espelhados do contrato; validação definitiva permanece no backend. */
export function prepareAssistantRequest(operation:AssistantOperation,input:string):AssistantRequest{
 const text=input.trim();if(!text)throw new Error("Escreva um contexto antes de continuar.");
 if(text.length>24000)throw new Error("Use no máximo 24.000 caracteres.");
 if(operation==="command"){if(text.length>1000)throw new Error("Use no máximo 1.000 caracteres para um comando.");return {command:text};}
 if(operation!=="batch-clean")return {text};
 let rows:unknown;try{rows=JSON.parse(text);}catch{throw new Error("Cole um array JSON válido, como [{\"nome\":\" Ana \"}].");}
 if(!Array.isArray(rows)||!rows.length||rows.length>100)throw new Error("Informe entre 1 e 100 linhas em um array JSON.");
 for(const row of rows){if(!row||typeof row!=="object"||Array.isArray(row)||Object.keys(row).length>50)throw new Error("Cada linha deve ser um objeto com até 50 colunas.");if(Object.values(row).some(v=>v!==null&&!["string","number","boolean"].includes(typeof v)))throw new Error("Células aceitam apenas texto, número, booleano ou null.");}
 return {rows:rows as AssistantRow[]};
}
