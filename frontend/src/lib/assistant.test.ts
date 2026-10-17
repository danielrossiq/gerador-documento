import { describe, expect, it } from "vitest";
import { prepareAssistantRequest } from "./assistant";
describe("assistant request contract", () => {
 it.each(["template", "extract", "review"] as const)("sends trimmed text for %s", operation => {
  expect(prepareAssistantRequest(operation, "  Documento  ")).toEqual({text: "Documento"});
 });
 it("uses command rather than text", () => {
  expect(prepareAssistantRequest("command", " Ajustar título ")).toEqual({command:"Ajustar título"});
 });
 it("preserves scalar batch cells for backend preview", () => {
  expect(prepareAssistantRequest("batch-clean", '[{"nome":" Ana ","n":2,"ok":true,"v":null}]')).toEqual({rows:[{nome:" Ana ",n:2,ok:true,v:null}]});
 });
 it("rejects empty input and excessive command length", () => {
  expect(() => prepareAssistantRequest("review", "  ")).toThrow();
  expect(() => prepareAssistantRequest("command", "x".repeat(1001))).toThrow();
 });
 it.each(['{}','[]','[null]','[[1]]','[{"nested":{}}]','invalid'])("rejects invalid rows: %s", input => {
  expect(() => prepareAssistantRequest("batch-clean",input)).toThrow();
 });
 it("rejects more than 100 batch rows", () => {
  expect(() => prepareAssistantRequest("batch-clean",JSON.stringify(Array.from({length:101},()=>({a:1}))))).toThrow();
 });
});
