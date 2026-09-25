/**
 * Tests for the landing page's pure URL/code parsing — the deep-link and
 * join-code validation. DOM building is dogfood-verified.
 */
import { describe, expect, it } from "vitest";
import { parseRoomCode, roomDeepLink, roomFromSearch } from "./landing";

describe("parseRoomCode", () => {
  it("accepts four alphanumeric characters and uppercases", () => {
    expect(parseRoomCode("ab2f")).toBe("AB2F");
    expect(parseRoomCode("  X9Z1 ")).toBe("X9Z1");
  });

  it("rejects wrong lengths and non-alphanumerics", () => {
    expect(parseRoomCode("abc")).toBeNull();
    expect(parseRoomCode("abcde")).toBeNull();
    expect(parseRoomCode("ab-f")).toBeNull();
    expect(parseRoomCode("")).toBeNull();
  });
});

describe("roomFromSearch (the ?room= deep link)", () => {
  it("reads and normalizes the room param", () => {
    expect(roomFromSearch("?room=ab2f")).toBe("AB2F");
    expect(roomFromSearch("?name=Zed&room=AB2F")).toBe("AB2F");
  });

  it("returns null without a param or with a junk one", () => {
    expect(roomFromSearch("")).toBeNull();
    expect(roomFromSearch("?name=Zed")).toBeNull();
    expect(roomFromSearch("?room=TOOLONG")).toBeNull();
  });
});

describe("roomDeepLink", () => {
  it("builds a shareable link that round-trips through roomFromSearch", () => {
    const link = roomDeepLink("AB2F", "https://example.test");
    expect(link).toBe("https://example.test/?room=AB2F");
    expect(roomFromSearch(new URL(link).search)).toBe("AB2F");
  });
});
