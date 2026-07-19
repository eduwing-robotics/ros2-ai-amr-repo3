export function OperationIcon({ operation }: { operation: string }) {
  const normalized = operation === "inbound" ? "inbound" : "outbound";
  const inbound = normalized === "inbound";

  return (
    <svg
      className={`operation-icon operation-icon-${normalized}`}
      viewBox="0 0 20 20"
      aria-hidden="true"
    >
      <path d="M4 11.5v4h12v-4" />
      <path d={inbound ? "M10 3v9m-3-3 3 3 3-3" : "M10 13V4m-3 3 3-3 3 3"} />
    </svg>
  );
}
