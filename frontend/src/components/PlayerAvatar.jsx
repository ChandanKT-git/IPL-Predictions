import React, { useState } from "react";
import { getImageUrl } from "../lib/api";

const ROLE_ICON = {
  Batsman: "🏏",
  Bowler: "⚡",
  "All-rounder": "★",
  "Wicket-keeper": "✧",
};

const initials = (name) =>
  name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0])
    .join("")
    .toUpperCase();

/**
 * Player avatar with multiple fallback strategies:
 * 1. Cricbuzz image (if imageId provided)
 * 2. SVG with player initials over team colors
 */
export const PlayerAvatar = ({ player, team, size = 64 }) => {
  const [imageError, setImageError] = useState(false);

  if (!player || !team) return null;

  // Use Cricbuzz image if available
  if (player.imageId && !imageError) {
    return (
      <div
        className="overflow-hidden rounded-xl border border-white/10"
        style={{ width: size, height: size }}
      >
        <img
          src={getImageUrl(player.imageId)}
          alt={player.name}
          className="object-cover w-full h-full"
          onError={() => setImageError(true)}
        />
      </div>
    );
  }

  // SVG fallback with player initials
  const gradientId = `pg-${team.id}-${player.name.replace(/\s/g, "")}`;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      aria-label={player.name}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={team.primary_color} />
          <stop offset="100%" stopColor={team.secondary_color} />
        </linearGradient>
      </defs>
      <rect x="3" y="3" width="94" height="94" rx="14" fill={`url(#${gradientId})`} />
      <rect
        x="3"
        y="3"
        width="94"
        height="94"
        rx="14"
        fill="none"
        stroke="rgba(255,255,255,0.2)"
        strokeWidth="1"
      />
      <text
        x="50"
        y="58"
        textAnchor="middle"
        fontFamily="Oswald, sans-serif"
        fontWeight="700"
        fontSize="36"
        fill="#fff"
      >
        {initials(player.name)}
      </text>
    </svg>
  );
};

export const RoleIcon = ({ role }) => (
  <span aria-hidden className="text-[10px]">
    {ROLE_ICON[role] || "•"}
  </span>
);

export default PlayerAvatar;
