import { AuditsDashboard } from "../../../components/AuditsDashboard";

export default async function AuditRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AuditsDashboard runId={id} />;
}
