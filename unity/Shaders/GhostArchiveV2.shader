// GhostArchive.shader — one draw call renders every ghost in its captured pose.
// Mesh: N copies of the low-poly rig (see GhostMeshBuilder). Per vertex:
//   POSITION  rest position, rig space, hips at origin
//   NORMAL
//   TEXCOORD1 (x,y) = bone index 0, bone index 1
//   COLOR.r   = weight of bone 0 (bone 1 gets 1-r)
//   TEXCOORD2.x = ghost index (row in _PoseTex)
// Opaque cutout with Bayer dither: age -> sparser ghost. No transparency, writes depth.
// V2: two pose textures, same single draw call. Ghost index i < _BaseCount reads _PoseTex (baked
// into the world); i >= _NewStart reads _PoseTexNew (downloaded) at row i - _NewStart. Pose layout unchanged.
Shader "AshenChoir/GhostArchiveV2"
{
    Properties
    {
        _PoseTex     ("Base Pose Texture (baked)", 2D) = "black" {}
        _PoseRows    ("Base Pose Rows", Float) = 64
        _BaseCount   ("Base Ghost Count", Float) = 0
        _PoseTexNew  ("New Pose Texture (downloaded)", 2D) = "black" {}
        _PoseRowsNew ("New Pose Rows", Float) = 64
        _NewStart    ("First ghost index in new texture", Float) = 0
        _GhostCount  ("Ghost Count (total)", Float) = 0
        _TodayDay    ("Today (days since 2020)", Float) = 0
        _FadeDays    ("Days until fully faded", Float) = 730
        _MinPresence ("Min presence (oldest ghosts)", Range(0,1)) = 0.08
        _Color       ("Base Color", Color) = (0.75, 0.72, 0.85, 1)
        _Emission    ("Emission (grows with age)", Color) = (0.55, 0.35, 0.9, 1)
        _EmissionAge ("Emission strength at max age", Float) = 1.5
        _LinearizeSRGB    ("Base pose tex is sRGB (undo it)", Float) = 0
        _LinearizeSRGBNew ("New pose tex is sRGB (undo it)", Float) = 1
    }

    SubShader
    {
        Tags { "RenderType"="TransparentCutout" "Queue"="AlphaTest" "DisableBatching"="True" }
        Cull Back

        Pass
        {
            Tags { "LightMode"="ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fwdbase
            #pragma target 3.5
            #include "UnityCG.cginc"
            #include "Lighting.cginc"
            #include "GhostRig.cginc"

            sampler2D _PoseTex, _PoseTexNew;
            float _PoseRows, _PoseRowsNew, _BaseCount, _NewStart, _GhostCount;
            float _TodayDay, _FadeDays, _MinPresence;
            float4 _Color, _Emission;
            float _EmissionAge, _LinearizeSRGB, _LinearizeSRGBNew;


            struct appdata
            {
                float4 vertex : POSITION;
                float3 normal : NORMAL;
                float2 bones  : TEXCOORD1;
                float4 color  : COLOR;
                float2 ghost  : TEXCOORD2;
            };
            struct v2f
            {
                float4 pos      : SV_POSITION;
                float3 wnormal  : TEXCOORD0;
                float4 spos     : TEXCOORD1;
                float  fade     : TEXCOORD2;
                float3 sh       : TEXCOORD3;
            };

            // ---------- pose texture decode ----------
            float srgbToLinearInv(float c) // linear -> sRGB byte space
            {
                return c <= 0.0031308 ? c * 12.92 : 1.055 * pow(c, 1.0 / 2.4) - 0.055;
            }
            float4 readPx(int px, float v, bool isNew)
            {
                float4 uv = float4((px + 0.5) / 64.0, v, 0, 0);
                float4 c;
                float lin;
                [branch] if (isNew) { c = tex2Dlod(_PoseTexNew, uv); lin = _LinearizeSRGBNew; }
                else               { c = tex2Dlod(_PoseTex, uv);    lin = _LinearizeSRGB; }
                if (lin > 0.5)
                    c = float4(srgbToLinearInv(c.r), srgbToLinearInv(c.g), srgbToLinearInv(c.b), c.a);
                return c;
            }
            // two uint16 values per pixel: (R lo, G hi), (B lo, A hi)
            float2 read2(int px, float v, bool isNew)
            {
                float4 c = round(readPx(px, v, isNew) * 255.0);
                return float2(c.r + c.g * 256.0, c.b + c.a * 256.0);
            }

            // ---------- rotation helpers ----------
            // Rotate v by the shortest rotation taking unit vector a to unit vector b.
            float3 rotateFromTo(float3 v, float3 a, float3 b)
            {
                float3 axis = cross(a, b);
                float s2 = dot(axis, axis);
                float c = dot(a, b);
                if (s2 < 1e-8)
                {
                    if (c > 0) return v;
                    // 180 degrees: pick any perpendicular axis
                    float3 p = abs(a.y) < 0.9 ? float3(0,1,0) : float3(1,0,0);
                    axis = normalize(cross(a, p));
                    return 2.0 * dot(v, axis) * axis - v;
                }
                float s = sqrt(s2);
                float3 k = axis / s;
                // Rodrigues
                return v * c + cross(k, v) * s + k * dot(k, v) * (1 - c);
            }
            float3x3 basisFrom(float3 right, float3 up)
            {
                right = normalize(right);
                float3 fwd = normalize(cross(right, up));
                up = cross(fwd, right);
                return float3x3(right, up, fwd); // rows
            }

            v2f vert(appdata i)
            {
                v2f o;
                float ghostIdx = floor(i.ghost.x + 0.5);
                bool isNew = ghostIdx >= _BaseCount;
                float row = isNew ? ghostIdx - _NewStart : ghostIdx;
                float rows = isNew ? _PoseRowsNew : _PoseRows;
                // Not rendered (beyond count, or a gap between base and new): collapse to a degenerate point
                if (ghostIdx >= _GhostCount || row < 0 || row >= rows)
                {
                    o.pos = float4(0, 0, -2, 1);
                    o.wnormal = 0; o.spos = 0; o.fade = 1; o.sh = 0;
                    return o;
                }
                float v = (row + 0.5) / rows;

                // Root and height
                float2 p0 = read2(0, v, isNew), p1 = read2(1, v, isNew);
                if (p1.y < 1)
                {
                    // Empty row (tsv and png briefly out of step during a refresh): don't draw
                    o.pos = float4(0, 0, -2, 1);
                    o.wnormal = 0; o.spos = 0; o.fade = 1; o.sh = 0;
                    return o;
                }
                float3 root = float3(p0.x, p0.y, p1.x) - 32768.0;
                root *= 0.008; // 8 mm units
                float heightM = p1.y * 0.001;
                float scale = max(0.2, heightM / GHOST_RIG_EYE_HEIGHT);

                // Captured bone positions (hips relative, metres)
                float3 P[GHOST_BONES];
                [unroll]
                for (int b = 0; b < GHOST_BONES; b++)
                {
                    float2 xy = read2(2 + 2 * b, v, isNew);
                    float2 z0 = read2(3 + 2 * b, v, isNew);
                    P[b] = (float3(xy.x, xy.y, z0.x) - 32768.0) * 0.001;
                }

                // Re-pose the rig: keep rig limb lengths, take captured directions
                float3 N[GHOST_BONES];
                N[0] = 0;
                [unroll]
                for (int j = 1; j < GHOST_BONES; j++)
                {
                    int par = GHOST_PARENT[j];
                    float3 dRest = GHOST_REST[j] - GHOST_REST[par];
                    float3 dCap  = P[j] - P[par];
                    bool missing = dot(P[j], P[j]) < 1e-8 || dot(dCap, dCap) < 1e-6;
                    float3 dir = missing ? normalize(dRest) : normalize(dCap);
                    N[j] = N[par] + dir * length(dRest);
                }

                // Skin this vertex
                int b0 = (int)(i.bones.x + 0.5);
                int b1 = (int)(i.bones.y + 0.5);
                float w0 = i.color.r;
                float w1 = 1.0 - w0;

                float3 pos = 0, nrm = 0;
                [unroll]
                for (int k = 0; k < 2; k++)
                {
                    int bi = k == 0 ? b0 : b1;
                    float w = k == 0 ? w0 : w1;
                    if (w <= 0.0001) continue;

                    float3 local = i.vertex.xyz - GHOST_REST[bi];
                    float3 rotated, rotatedN;

                    if (bi == 0)
                    {
                        // Hips: full basis from leg spread (right) and spine (up)
                        float3x3 r0 = basisFrom(GHOST_REST[16] - GHOST_REST[13], GHOST_REST[1] - GHOST_REST[0]);
                        float3x3 r1 = basisFrom(N[16] - N[13], N[1] - N[0]);
                        rotated  = mul(transpose(r1), mul(r0, local));
                        rotatedN = mul(transpose(r1), mul(r0, i.normal));
                    }
                    else
                    {
                        int child = GHOST_SEG_CHILD[bi];
                        int par = GHOST_PARENT[bi];
                        float3 s0 = child >= 0 ? GHOST_REST[child] - GHOST_REST[bi] : GHOST_REST[bi] - GHOST_REST[par];
                        float3 s1 = child >= 0 ? N[child] - N[bi] : N[bi] - N[par];
                        s0 = normalize(s0); s1 = normalize(s1);
                        rotated  = rotateFromTo(local, s0, s1);
                        rotatedN = rotateFromTo(i.normal, s0, s1);
                    }
                    pos += (N[bi] + rotated) * w;
                    nrm += rotatedN * w;
                }

                float3 wpos = mul(unity_ObjectToWorld, float4(root + pos * scale, 1)).xyz;
                o.pos = UnityWorldToClipPos(wpos);
                o.wnormal = normalize(mul((float3x3)unity_ObjectToWorld, normalize(nrm)));
                o.spos = ComputeScreenPos(o.pos);
                o.sh = ShadeSH9(float4(o.wnormal, 1));

                // Age
                float2 meta = read2(40, v, isNew);
                float age = max(0, _TodayDay - meta.x);
                o.fade = saturate(age / max(1.0, _FadeDays));
                return o;
            }

            float bayer4(float2 p)
            {
                int2 q = int2(fmod(floor(p), 4.0));
                int idx = q.x + q.y * 4;
                const float m[16] = { 0,8,2,10, 12,4,14,6, 3,11,1,9, 15,7,13,5 };
                return (m[idx] + 0.5) / 16.0;
            }

            fixed4 frag(v2f i) : SV_Target
            {
                float2 sp = i.spos.xy / i.spos.w * _ScreenParams.xy;
                float presence = lerp(1.0, _MinPresence, i.fade);
                clip(presence - bayer4(sp));

                float3 n = normalize(i.wnormal);
                float ndl = saturate(dot(n, _WorldSpaceLightPos0.xyz));
                float3 lit = _Color.rgb * (_LightColor0.rgb * ndl + i.sh);
                float3 em = _Emission.rgb * _EmissionAge * i.fade;
                return fixed4(lit + em, 1);
            }
            ENDCG
        }
    }
    Fallback Off
}
