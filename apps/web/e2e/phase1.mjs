import { chromium } from "playwright";

const baseURL = process.env.PHASE1_WEB_URL || "http://localhost:3000";
const apiURL = (process.env.PHASE1_API_URL || "http://localhost:8000/api/v1").replace(/\/$/, "");
const apiOrigin = new URL(apiURL).origin;
const browserOrigin = new URL(baseURL).origin;
const email = `phase1-${Date.now()}@example.com`;
const password = "phase1-password";
const browser = await chromium.launch();
const context = await browser.newContext();
const page = await context.newPage();
const eventRequests = [];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function expectStatus(response, expected, label) {
  assert(response.status() === expected, `${label}: expected ${expected}, received ${response.status()}`);
  return response;
}

async function requestJson(method, path, options = {}) {
  const response = await context.request.fetch(`${apiURL}${path}`, { method, ...options });
  return { response, body: await response.json().catch(() => null) };
}

page.on("request", (request) => {
  if (request.url().includes("/events")) eventRequests.push(request.url());
});

try {
  await page.goto(`${baseURL}/register`);
  await page.getByLabel("Full Name").fill("Phase 1 Tester");
  await page.getByLabel("Email Address").fill(email);
  await page.getByLabel("Password").fill(password);
  const registerResponsePromise = page.waitForResponse(
    (response) => response.url() === `${apiURL}/auth/register` && response.request().method() === "POST"
  );
  await page.getByRole("button", { name: "Sign Up" }).click();
  const registerResponse = await registerResponsePromise;
  const registerBody = await registerResponse.json();
  assert(!registerBody.access_token, "registration exposed a raw access token");
  await page.waitForURL(/\/account$/);

  const cookies = await context.cookies();
  const sessionCookie = cookies.find((cookie) => cookie.name === "triphony_session");
  assert(sessionCookie?.httpOnly, "session cookie is not HttpOnly");
  assert(!page.url().includes("token"), "browser URL contains a token");
  const storage = await page.evaluate(() => Object.keys(localStorage));
  assert(!storage.some((key) => /token|jwt|auth/i.test(key)), "browser storage contains an auth token");

  await page.goto(`${baseURL}/studio`);
  await page.getByPlaceholder("Describe your scene...").fill("A neon city after rain");
  const createResponsePromise = page.waitForResponse(
    (response) => response.url() === `${apiURL}/scenes` && response.request().method() === "POST"
  );
  await page.getByRole("button", { name: "Generate Scene" }).click();
  const createResponse = await createResponsePromise;
  const { scene_id: sceneId } = await createResponse.json();
  assert(sceneId, "scene creation did not return an id");

  const early = await requestJson("GET", `/scenes/${sceneId}`);
  await expectStatus(early.response, 200, "initial scene fetch");
  assert(["queued", "running", "done"].includes(early.body.status), "scene entered an invalid initial state");

  await page.locator("video").waitFor({ state: "visible", timeout: 30_000 });
  await page.locator("audio").waitFor({ state: "visible", timeout: 30_000 });
  await page.locator(".narrativeText").waitFor({ state: "visible", timeout: 30_000 });
  await page.getByText("Done.").waitFor({ state: "visible", timeout: 30_000 });

  const sceneResult = await requestJson("GET", `/scenes/${sceneId}`);
  await expectStatus(sceneResult.response, 200, "completed scene fetch");
  assert(sceneResult.body.status === "done", "scene did not reach done state");
  assert(sceneResult.body.workflow_state === "completed", "workflow did not reach completed state");
  assert(sceneResult.body.final_render?.status === "succeeded", "final render was not persisted");
  const visual = sceneResult.body.assets.find((asset) => asset.asset_type === "visual");
  const soundtrack = sceneResult.body.assets.find((asset) => asset.asset_type === "soundtrack");
  const narrative = sceneResult.body.assets.find((asset) => asset.asset_type === "narrative");
  assert(visual?.status === "succeeded" && visual.mime_type === "video/mp4", "mock video was not completed as MP4");
  assert(soundtrack?.status === "succeeded" && soundtrack.mime_type === "audio/wav", "mock audio was not completed as WAV");
  assert(narrative?.status === "succeeded" && narrative.content_text.includes("A neon city after rain"), "mock narrative was not persisted");
  const finalRender = await context.request.get(`${apiOrigin}${sceneResult.body.final_render.artifact_url}`);
  await expectStatus(finalRender, 200, "final render delivery");
  assert((finalRender.headers()["content-type"] || "").startsWith("video/mp4"), "final render MIME type was not MP4");
  assert(eventRequests.length > 0 && eventRequests.every((url) => !url.includes("token=")), "SSE used a token in its URL");

  const video = page.locator("video");
  await page.waitForFunction(() => {
    const media = document.querySelector("video");
    return media?.readyState >= 1 && Number.isFinite(media.duration) && media.duration > 0;
  });
  await video.evaluate((element) => {
    const media = element;
    media.muted = true;
    return media.play();
  });
  await page.waitForFunction(() => (document.querySelector("video")?.currentTime || 0) > 0, null, { timeout: 5_000 });
  const videoState = await video.evaluate((element) => ({ duration: element.duration, currentTime: element.currentTime }));
  assert(videoState.duration > 0 && videoState.currentTime > 0, "mock video did not advance playback");

  const audio = page.locator("audio");
  await page.waitForFunction(() => {
    const media = document.querySelector("audio");
    return media?.readyState >= 1 && Number.isFinite(media.duration) && media.duration > 0;
  });
  await audio.evaluate((element) => {
    const media = element;
    media.muted = true;
    return media.play();
  });
  await page.waitForFunction(() => (document.querySelector("audio")?.currentTime || 0) > 0, null, { timeout: 5_000 });
  const audioState = await audio.evaluate((element) => ({ duration: element.duration, currentTime: element.currentTime }));
  assert(audioState.duration > 0 && audioState.currentTime > 0, "mock audio did not advance playback");

  const range = await context.request.get(`${apiURL}/artifacts/${visual.id}`, { headers: { Range: "bytes=0-31" } });
  await expectStatus(range, 206, "video range request");
  assert((range.headers()["content-range"] || "").startsWith("bytes 0-31/"), "video range response was malformed");

  await page.reload();
  await page.goto(`${baseURL}/library`);
  await page.getByText("A neon city after rain").waitFor({ state: "visible" });
  await page.getByRole("link", { name: "Open" }).click();
  await page.locator("video").waitFor({ state: "visible", timeout: 30_000 });

  const otherContext = await browser.newContext();
  const otherPage = await otherContext.newPage();
  try {
    const otherEmail = `phase1-other-${Date.now()}@example.com`;
    await otherPage.goto(`${baseURL}/register`);
    await otherPage.getByLabel("Full Name").fill("Other User");
    await otherPage.getByLabel("Email Address").fill(otherEmail);
    await otherPage.getByLabel("Password").fill(password);
    await otherPage.getByRole("button", { name: "Sign Up" }).click();
    await otherPage.waitForURL(/\/account$/);

    const otherScene = await otherContext.request.get(`${apiURL}/scenes/${sceneId}`);
    await expectStatus(otherScene, 404, "cross-user scene access");
    const otherLibrary = await otherContext.request.get(`${apiURL}/scenes`);
    await expectStatus(otherLibrary, 200, "cross-user library access");
    const otherLibraryBody = await otherLibrary.json();
    assert(Array.isArray(otherLibraryBody) && otherLibraryBody.length === 0, "cross-user library leaked scenes");
    const otherEvents = await otherContext.request.get(`${apiURL}/scenes/${sceneId}/events`);
    await expectStatus(otherEvents, 404, "cross-user SSE access");
    const otherArtifact = await otherContext.request.get(`${apiURL}/artifacts/${visual.id}`);
    await expectStatus(otherArtifact, 404, "cross-user artifact access");
    const otherFinalRender = await otherContext.request.get(`${apiOrigin}${sceneResult.body.final_render.artifact_url}`);
    await expectStatus(otherFinalRender, 404, "cross-user final render access");
    for (const asset of [narrative, visual, soundtrack]) {
      const response = await otherContext.request.get(`${apiURL}/artifacts/${asset.id}`);
      await expectStatus(response, 404, `cross-user ${asset.asset_type} access`);
      const ranged = await otherContext.request.get(`${apiURL}/artifacts/${asset.id}`, { headers: { Range: "bytes=0-3" } });
      await expectStatus(ranged, 404, `cross-user ${asset.asset_type} range access`);
    }

    await new Promise((resolve) => setTimeout(resolve, 5_100));
    const cancelCookies = await otherContext.cookies();
    const cancelCsrf = cancelCookies.find((cookie) => cookie.name === "triphony_csrf")?.value;
    const cancelHeaders = {
      "Content-Type": "application/json",
      "X-CSRF-Token": cancelCsrf,
      Origin: browserOrigin,
    };
    const cancelCreate = await otherContext.request.post(`${apiURL}/scenes`, {
      headers: cancelHeaders,
      data: JSON.stringify({ prompt: "Cancel this queued scene" }),
    });
    await expectStatus(cancelCreate, 200, "cancellation scene creation");
    const cancelSceneId = (await cancelCreate.json()).scene_id;
    const cancelResponse = await otherContext.request.post(`${apiURL}/scenes/${cancelSceneId}/cancel`, { headers: cancelHeaders });
    await expectStatus(cancelResponse, 200, "owned cancellation");
    const repeatCancel = await otherContext.request.post(`${apiURL}/scenes/${cancelSceneId}/cancel`, { headers: cancelHeaders });
    await expectStatus(repeatCancel, 200, "idempotent cancellation");
    const cancelledScene = await otherContext.request.get(`${apiURL}/scenes/${cancelSceneId}`);
    await expectStatus(cancelledScene, 200, "cancelled scene fetch");
    assert((await cancelledScene.json()).workflow_state === "cancelled", "cancellation did not persist");
    const otherUserCancel = await context.request.post(`${apiURL}/scenes/${cancelSceneId}/cancel`, {
      headers: { "X-CSRF-Token": (await context.cookies()).find((cookie) => cookie.name === "triphony_csrf")?.value, Origin: browserOrigin },
    });
    await expectStatus(otherUserCancel, 404, "cross-user cancellation denial");
  } finally {
    await otherContext.close();
  }

  const anonymousContext = await browser.newContext();
  try {
    const anonymousArtifact = await anonymousContext.request.get(`${apiURL}/artifacts/${visual.id}`);
    await expectStatus(anonymousArtifact, 401, "unauthenticated artifact access");
  } finally {
    await anonymousContext.close();
  }

  await page.goto(`${baseURL}/account`);
  await page.getByRole("button", { name: "Log Out" }).click();
  await page.waitForURL(`${baseURL}/`);
  const afterLogout = await context.request.get(`${apiURL}/scenes`);
  await expectStatus(afterLogout, 401, "protected route after logout");
  assert(!(await context.cookies()).some((cookie) => cookie.name === "triphony_session"), "logout did not clear the session cookie");
  console.log("Phase 1 browser acceptance passed");
} finally {
  await context.close();
  await browser.close();
}
