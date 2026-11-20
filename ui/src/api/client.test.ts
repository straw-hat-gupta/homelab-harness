import { ApiError, createApi, ownerToken, uiApi } from "@/api/client";
import { tree } from "@/test/fixtures";

function harness(status: number, body: unknown) {
  const calls: Request[] = [];
  const fetchImpl = (request: Request) => {
    calls.push(request);
    return Promise.resolve(Response.json(body, { status }));
  };
  return { calls, api: uiApi(createApi("http://harness", fetchImpl as typeof fetch)) };
}

describe("the UI API client", () => {
  afterEach(() => {
    ownerToken.clear();
  });

  it("sends the owner token and returns typed data", async () => {
    ownerToken.set("hh-owner-test");
    const { calls, api } = harness(200, tree);
    await expect(api.tree()).resolves.toEqual(tree);
    expect(calls[0]?.url).toBe("http://harness/api/ui/tree");
    expect(calls[0]?.headers.get("Authorization")).toBe("Bearer hh-owner-test");
  });

  it("sends no Authorization header without a token", async () => {
    const { calls, api } = harness(200, tree);
    await api.tree();
    expect(calls[0]?.headers.has("Authorization")).toBe(false);
  });

  it("builds the summary path from the object type and id", async () => {
    const { calls, api } = harness(200, {});
    await api.summary("storage", "home:pve1:local-zfs");
    expect(new URL(calls[0]?.url ?? "").pathname).toBe(
      "/api/ui/objects/storage/home%3Apve1%3Alocal-zfs/summary",
    );
  });

  it.each([
    [401, { detail: "an owner token is required" }, "an owner token is required"],
    [502, { detail: "the cluster did not answer" }, "the cluster did not answer"],
    [500, "not json detail", "the harness could not answer"],
  ])("turns a %i into an ApiError with the server's safe detail", async (status, body, message) => {
    const { api } = harness(status, body);
    const error = await api.tree().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status, message });
  });
});
