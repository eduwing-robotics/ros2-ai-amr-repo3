import { useId } from "react";
import {
  exampleFor,
  resolveSchema,
  type OpenApiDoc,
  type OpenApiSchema,
} from "../lib/openApiForm";

function fieldLabel(name: string, schema: OpenApiSchema): string {
  return schema.title || name;
}

function SchemaField({
  name,
  schema,
  value,
  onChange,
  doc,
  required,
  depth = 0,
}: {
  name: string;
  schema: OpenApiSchema;
  value: any;
  onChange: (v: any) => void;
  doc: OpenApiDoc;
  required?: boolean;
  depth?: number;
}) {
  const resolved = resolveSchema(schema, doc) ?? schema;
  const label = fieldLabel(name, resolved);
  const req = required ? " *" : "";

  if (resolved.enum) {
    return (
      <label className="schema-field">
        <span className="schema-label mono">{label}{req}</span>
        <select className="filter" value={String(value ?? resolved.enum[0])} onChange={(e) => onChange(e.target.value)}>
          {resolved.enum.map((opt: string) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      </label>
    );
  }

  if (resolved.type === "boolean") {
    return (
      <label className="schema-field schema-field-check">
        <span className="schema-label mono">{label}{req}</span>
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
      </label>
    );
  }

  if (resolved.type === "integer" || resolved.type === "number") {
    return (
      <label className="schema-field">
        <span className="schema-label mono">{label}{req}</span>
        <input
          className="search mono"
          type="number"
          step={resolved.type === "integer" ? 1 : "any"}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
        />
      </label>
    );
  }

  if (resolved.type === "array") {
    const items: any[] = Array.isArray(value) ? value : [];
    const itemSchema = resolved.items as OpenApiSchema | undefined;
    return (
      <fieldset className="schema-group">
        <legend className="schema-label mono">{label}{req}</legend>
        {items.map((item, i) => (
          <div key={i} className="schema-array-row">
            <SchemaField
              name={`${name}[${i}]`}
              schema={itemSchema ?? { type: "string" }}
              value={item}
              onChange={(v) => {
                const next = [...items];
                next[i] = v;
                onChange(next);
              }}
              doc={doc}
              depth={depth + 1}
            />
            <button type="button" className="rowbtn" onClick={() => onChange(items.filter((_, j) => j !== i))}>삭제</button>
          </div>
        ))}
        <button
          type="button"
          className="rowbtn"
          onClick={() => onChange([...items, exampleFor(itemSchema, doc) ?? ""])}
        >
          + 항목
        </button>
      </fieldset>
    );
  }

  if (resolved.type === "object" || resolved.properties) {
    const obj = (value && typeof value === "object" && !Array.isArray(value) ? value : {}) as Record<string, any>;
    const reqSet = new Set<string>(resolved.required ?? []);
    return (
      <fieldset className={`schema-group${depth ? " nested" : ""}`}>
        <legend className="schema-label mono">{label}{req}</legend>
        {Object.entries(resolved.properties ?? {}).map(([key, child]) => (
          <SchemaField
            key={key}
            name={key}
            schema={child as OpenApiSchema}
            value={obj[key]}
            onChange={(v) => onChange({ ...obj, [key]: v })}
            doc={doc}
            required={reqSet.has(key)}
            depth={depth + 1}
          />
        ))}
      </fieldset>
    );
  }

  const union = resolved.anyOf || resolved.oneOf;
  if (union?.length) {
    const pick = union.find((s: OpenApiSchema) => s.type !== "null") ?? union[0];
    return (
      <SchemaField name={name} schema={pick} value={value} onChange={onChange} doc={doc} required={required} depth={depth} />
    );
  }

  return (
    <label className="schema-field">
      <span className="schema-label mono">{label}{req}</span>
      <input
        className="search mono"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={resolved.format || "string"}
      />
    </label>
  );
}

/** OpenAPI bodySchema 기반 범용 본문 폼 (PHASE_49-B). */
export function SchemaForm({
  schema,
  doc,
  value,
  onChange,
}: {
  schema: OpenApiSchema;
  doc: OpenApiDoc;
  value: any;
  onChange: (v: any) => void;
}) {
  const rootId = useId();
  const resolved = resolveSchema(schema, doc) ?? schema;
  const reqSet = new Set<string>(resolved.required ?? []);

  if (resolved.type === "object" || resolved.properties) {
    const obj = (value && typeof value === "object" && !Array.isArray(value) ? value : {}) as Record<string, any>;
    return (
      <div className="schema-form" id={rootId}>
        {Object.entries(resolved.properties ?? {}).map(([key, child]) => (
          <SchemaField
            key={key}
            name={key}
            schema={child as OpenApiSchema}
            value={obj[key]}
            onChange={(v) => onChange({ ...obj, [key]: v })}
            doc={doc}
            required={reqSet.has(key)}
          />
        ))}
      </div>
    );
  }

  return (
    <SchemaField name="body" schema={resolved} value={value} onChange={onChange} doc={doc} required />
  );
}
