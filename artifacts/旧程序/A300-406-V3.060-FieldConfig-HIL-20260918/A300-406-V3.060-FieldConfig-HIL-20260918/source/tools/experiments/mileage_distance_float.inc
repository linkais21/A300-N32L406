/* Trial only. Keep coordinate subtraction in double to preserve small steps.
 * Standard float libm replaces double trigonometry; no fast-math flags.
 * This changes rounding at decision boundaries and is NOT a drop-in release.
 */
static double haversine_m(double lat1, double lon1, double lat2, double lon2)
{
    double delta_lon = lon2 - lon1;
    if (delta_lon > 180.0) delta_lon -= 360.0;
    else if (delta_lon < -180.0) delta_lon += 360.0;
    float half_lat = (float)((lat2 - lat1) * (M_PI / 360.0));
    float half_lon = (float)(delta_lon * (M_PI / 360.0));
    /* sin(colatitude) avoids cosf(pi/2) cancellation at the poles. */
    float cos_lat1 = sinf((float)((90.0 - fabs(lat1)) * (M_PI / 180.0)));
    float cos_lat2 = sinf((float)((90.0 - fabs(lat2)) * (M_PI / 180.0)));
    float s_lat = sinf(half_lat), s_lon = sinf(half_lon);
    float a = s_lat * s_lat + cos_lat1 * cos_lat2 * s_lon * s_lon;
    /* Roundoff near an antipode must not feed a negative value to sqrtf. */
    if (a > 1.0f) a = 1.0f;
    float angle = 2.0f * atan2f(sqrtf(a), sqrtf(1.0f - a));
    return EARTH_R_M * (double)angle;
}
