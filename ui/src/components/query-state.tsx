import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, ownerToken } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Asks for an owner token after a 401. **Interim** until passkey login
 * (ADR-0007): the token is kept for this tab only.
 */
export function OwnerTokenPrompt() {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const submit = (event: { preventDefault: () => void }) => {
    event.preventDefault();
    if (!value.trim()) return;
    ownerToken.set(value.trim());
    setValue("");
    void queryClient.invalidateQueries();
  };
  return (
    <form onSubmit={submit} className="space-y-2 text-sm">
      <p className="text-muted-foreground">
        The harness needs an owner token. Create one with{" "}
        <code className="font-mono">homelab-harness-token create --role owner</code>. Passkey login
        replaces this.
      </p>
      <div className="flex gap-2">
        <Input
          type="password"
          aria-label="Owner token"
          autoComplete="off"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
          }}
        />
        <Button type="submit">Sign in</Button>
      </div>
    </form>
  );
}

/** The owner-safe message of a failed query, or the token prompt on a 401. */
export function QueryError({ error }: { error: Error }) {
  if (error instanceof ApiError && error.status === 401) return <OwnerTokenPrompt />;
  return (
    <p role="alert" className="text-destructive text-sm">
      {error instanceof ApiError ? error.message : "The harness could not be reached."}
    </p>
  );
}
