import React, { useState } from "react";
import { getImageUrl } from "../lib/api";

// Static team logo URLs (official IPL team logos with multiple fallbacks)
const TEAM_LOGO_URLS = {
  mi: [
    "https://scores.iplt20.com/ipl/teamlogos/MI.png",
    "https://www.iplt20.com/assets/images/MI.png"
  ],
  csk: [
    "https://scores.iplt20.com/ipl/teamlogos/CSK.png",
    "https://www.iplt20.com/assets/images/CSK.png"
  ],
  rcb: [
    "https://scores.iplt20.com/ipl/teamlogos/RCB.png",
    "https://www.iplt20.com/assets/images/RCB.png"
  ],
  kkr: [
    "https://scores.iplt20.com/ipl/teamlogos/KKR.png",
    "https://www.iplt20.com/assets/images/KKR.png"
  ],
  dc: [
    "https://scores.iplt20.com/ipl/teamlogos/DC.png",
    "https://www.iplt20.com/assets/images/DC.png"
  ],
  srh: [
    "https://scores.iplt20.com/ipl/teamlogos/SRH.png",
    "https://www.iplt20.com/assets/images/SRH.png"
  ],
  pbks: [
    "https://scores.iplt20.com/ipl/teamlogos/PBKS.png",
    "https://www.iplt20.com/assets/images/PBKS.png"
  ],
  rr: [
    "https://scores.iplt20.com/ipl/teamlogos/RR.png",
    "https://www.iplt20.com/assets/images/RR.png"
  ],
  gt: [
    "https://scores.iplt20.com/ipl/teamlogos/GT.png",
    "https://www.iplt20.com/assets/images/GT.png"
  ],
  lsg: [
    "https://scores.iplt20.com/ipl/teamlogos/LSG.png",
    "https://www.iplt20.com/assets/images/LSG.png"
  ],
};

/**
 * Team logo component with multiple fallback strategies:
 * 1. Cricbuzz image (if imageId provided)
 * 2. Static IPL logos (with multiple sources)
 * 3. SVG with team colors and initials
 */
export const TeamLogo = ({ team, size = 64, className = "" }) => {
  const [imageError, setImageError] = useState(false);
  const [urlIndex, setUrlIndex] = useState(0);

  if (!team) return null;
  const { primary_color, secondary_color, short_name, imageId, id: teamId } = team;

  // Strategy 1: Use Cricbuzz image if available
  if (imageId && !imageError) {
    return (
      <div
        className={`rounded-full overflow-hidden border-2 border-white/10 ${className}`}
        style={{ width: size, height: size }}
      >
        <img
          src={getImageUrl(imageId)}
          alt={`${team.name} logo`}
          className="w-full h-full object-cover"
          onError={() => setImageError(true)}
        />
      </div>
    );
  }

  // Strategy 2: Use static IPL logo if available
  const logoUrls = teamId ? TEAM_LOGO_URLS[teamId] : null;
  if (logoUrls && !imageError && urlIndex < logoUrls.length) {
    return (
      <div
        className={`rounded-full overflow-hidden border-2 border-white/10 bg-white ${className}`}
        style={{ width: size, height: size }}
      >
        <img
          src={logoUrls[urlIndex]}
          alt={`${team.name} logo`}
          className="w-full h-full object-contain p-1"
          crossOrigin="anonymous"
          onError={() => {
            // Try next URL in the array
            if (urlIndex < logoUrls.length - 1) {
              setUrlIndex(urlIndex + 1);
            } else {
              setImageError(true);
            }
          }}
        />
      </div>
    );
  }

  // Strategy 3: SVG fallback with team colors
  const gradientId = `g-${teamId}`;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      className={className}
      aria-label={`${team.name} logo`}
      data-testid={`team-logo-${teamId}`}
    >
      <defs>
        <radialGradient id={gradientId} cx="30%" cy="30%" r="80%">
          <stop offset="0%" stopColor={secondary_color} stopOpacity="0.85" />
          <stop offset="60%" stopColor={primary_color} />
          <stop offset="100%" stopColor="#000" stopOpacity="0.85" />
        </radialGradient>
      </defs>
      <circle cx="50" cy="50" r="46" fill={`url(#${gradientId})`} stroke={secondary_color} strokeWidth="3" />
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
