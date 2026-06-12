import React from "react";
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

/** SVG avatar with player initials over team colors. Falls back to Cricbuzz image. */
export const PlayerAvatar = ({ player, team, size = 64 }) => {
  if (!player || !team) return null;

  if (player.imageId) {
    return (
      <div 
        className="overflow-hidden rounded-xl border border-white/10"
        style={{ width: size, height: size }}
      >
        <img 
          src={getImageUrl(player.imageId)} 
          alt={player.name}
          className="object-cover w-full h-full"
        />
      </div>
    );
  }

  const id = `pg-${team.id}-${player.name.replace(/\s/g, "")}`;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      aria-label={player.name}
    >
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={team.primary_color} />
          <stop offset="100%" stopColor={team.secondary_color} />
        </linearGradient>
      </defs>
      <rect x="3" y="3" width="94" height="94" rx="14" fill={`url(#${id})`} />
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
