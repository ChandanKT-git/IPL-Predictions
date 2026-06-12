import React from "react";
import { getImageUrl } from "../lib/api";

/**
 * Custom SVG team logo using initials over team colors.
 * Falls back to Cricbuzz image if imageId is provided.
 */
export const TeamLogo = ({ team, size = 64, className = "" }) => {
  if (!team) return null;
  const { primary_color, secondary_color, short_name, imageId } = team;

  if (imageId) {
    return (
      <div 
        className={`rounded-full overflow-hidden border-2 border-white/10 ${className}`}
        style={{ width: size, height: size }}
      >
        <img 
          src={getImageUrl(imageId)} 
          alt={`${team.name} logo`}
          className="w-full h-full object-cover"
        />
      </div>
    );
  }

  const id = `g-${team.id}`;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      className={className}
      aria-label={`${team.name} logo`}
      data-testid={`team-logo-${team.id}`}
    >
      <defs>
        <radialGradient id={id} cx="30%" cy="30%" r="80%">
          <stop offset="0%" stopColor={secondary_color} stopOpacity="0.85" />
          <stop offset="60%" stopColor={primary_color} />
          <stop offset="100%" stopColor="#000" stopOpacity="0.85" />
        </radialGradient>
      </defs>
      <circle cx="50" cy="50" r="46" fill={`url(#${id})`} stroke={secondary_color} strokeWidth="3" />
      <circle cx="50" cy="50" r="38" fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="1" />
      <text
        x="50"
        y="58"
        textAnchor="middle"
        fontFamily="Oswald, sans-serif"
        fontWeight="700"
        fontSize={short_name.length > 3 ? 22 : 28}
        fill="#fff"
        style={{ letterSpacing: "0.04em" }}
      >
        {short_name}
      </text>
    </svg>
  );
};

export default TeamLogo;
