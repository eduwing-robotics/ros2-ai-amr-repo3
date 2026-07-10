/** OpenAPI 스키마 → 예시/검증/폼 유틸*/

export type OpenApiSchema = Record<string, any>;
export interface OpenApiDoc { paths?: Record<string, Record<string, any>>; components?: { schemas?: Record<string, OpenApiSchema> } }

export function resolveRef(ref: string, doc: OpenApiDoc): OpenApiSchema | undefined {
  const name = ref.split("/").pop();
  return name ? doc.components?.schemas?.[name] : undefined;
}

export function resolveSchema(schema: OpenApiSchema | undefined, doc: OpenApiDoc, depth = 0): OpenApiSchema | undefined {
  if (!schema || depth > 8) return schema;
  if (schema.$ref) return resolveSchema(resolveRef(schema.$ref, doc), doc, depth + 1);
  return schema;
}

/** 스키마로부터 요청 본문 예시 골격 생성(깊이 제한). */
export function exampleFor(schema: OpenApiSchema | undefined, doc: OpenApiDoc, depth = 0): any {
  if (!schema || depth > 6) return null;
  const resolved = resolveSchema(schema, doc, depth);
  if (!resolved) return null;
  if (resolved.example !== undefined) return structuredClone(resolved.example);
  if (resolved.default !== undefined) return resolved.default;
  const union = resolved.anyOf || resolved.oneOf;
  if (union) return exampleFor(union.find((s: OpenApiSchema) => s.type !== "null") ?? union[0], doc, depth);
  if (resolved.enum) return resolved.enum[0];
  switch (resolved.type) {
    case "object": {
      const out: Record<string, any> = {};
      for (const [k, v] of Object.entries(resolved.properties || {})) out[k] = exampleFor(v as OpenApiSchema, doc, depth + 1);
      return out;
    }
    case "array": {
      const item = exampleFor(resolved.items, doc, depth + 1);
      return item === null ? [] : [item];
    }
    case "integer":
    case "number": return 0;
    case "boolean": return false;
    case "string": return resolved.format === "date-time" ? new Date().toISOString() : "";
    default: return null;
  }
}

export function schemaRequired(schema: OpenApiSchema | undefined, doc: OpenApiDoc): string[] {
  const resolved = resolveSchema(schema, doc);
  return resolved?.required ? [...resolved.required] : [];
}

/** 필수 필드 누락 메시지 목록. */
export function validateRequired(schema: OpenApiSchema | undefined, value: unknown, doc: OpenApiDoc, prefix = ""): string[] {
  const resolved = resolveSchema(schema, doc);
  if (!resolved) return [];
  const errors: string[] = [];
  const path = (key: string) => (prefix ? `${prefix}.${key}` : key);

  if (resolved.type === "object" || resolved.properties) {
    const obj = (value && typeof value === "object" && !Array.isArray(value) ? value : {}) as Record<string, unknown>;
    for (const key of schemaRequired(resolved, doc)) {
      const v = obj[key];
      if (v === undefined || v === null || v === "") errors.push(`필수 필드 "${path(key)}" 가 비어 있습니다.`);
    }
    for (const [key, child] of Object.entries(resolved.properties || {})) {
      if (obj[key] !== undefined) errors.push(...validateRequired(child as OpenApiSchema, obj[key], doc, path(key)));
    }
    return errors;
  }

  if (resolved.type === "array" && Array.isArray(value)) {
    value.forEach((item, i) => errors.push(...validateRequired(resolved.items, item, doc, `${prefix}[${i}]`)));
  }
  return errors;
}
