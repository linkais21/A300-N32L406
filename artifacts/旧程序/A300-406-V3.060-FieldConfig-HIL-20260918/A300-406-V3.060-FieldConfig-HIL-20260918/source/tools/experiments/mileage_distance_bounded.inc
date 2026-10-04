/* Trial only: bounded double-precision distance for mileage policy, not a
 * general navigation API. Valid geographic coordinates are required.
 * sin polynomial on [-pi/2, pi/2]: Taylor degree 19, exact-arithmetic omitted
 * term <= (pi/2)^21/21! < 2.6e-16. IEEE rounding is assessed separately.
 */
static double mileage_trial_sin(double x)
{
    double z = x * x;
    double p = -1.0 / 121645100408832000.0;
    p =  1.0 / 355687428096000.0 + z * p;
    p = -1.0 / 1307674368000.0 + z * p;
    p =  1.0 / 6227020800.0 + z * p;
    p = -1.0 / 39916800.0 + z * p;
    p =  1.0 / 362880.0 + z * p;
    p = -1.0 / 5040.0 + z * p;
    p =  1.0 / 120.0 + z * p;
    p = -1.0 / 6.0 + z * p;
    return x + x * z * p;
}

static double haversine_m(double lat1, double lon1, double lat2, double lon2)
{
    if (!(lat1 >= -90.0 && lat1 <= 90.0 && lat2 >= -90.0 && lat2 <= 90.0 &&
          lon1 >= -180.0 && lon1 <= 180.0 && lon2 >= -180.0 && lon2 <= 180.0))
        return NAN;
    double delta_lon = lon2 - lon1;
    if (delta_lon > 180.0) delta_lon -= 360.0;
    else if (delta_lon < -180.0) delta_lon += 360.0;
    double s_lat = mileage_trial_sin((lat2 - lat1) * (M_PI / 360.0));
    double s_lon = mileage_trial_sin(delta_lon * (M_PI / 360.0));
    double c1 = mileage_trial_sin((90.0 - fabs(lat1)) * (M_PI / 180.0));
    double c2 = mileage_trial_sin((90.0 - fabs(lat2)) * (M_PI / 180.0));
    double a = s_lat * s_lat + c1 * c2 * s_lon * s_lon;
    /* All distances >=8192 m reject mileage and exceed the maximum existing
     * uint16 stopdrift threshold /10 (6553.5 m). Their exact value is unused.
     * This cutoff must be revisited if those production contracts change. */
    if (a >= (8192.0 / (2.0 * EARTH_R_M)) * (8192.0 / (2.0 * EARTH_R_M)))
        return 8192.0;
    if (a <= 0.0) return 0.0;
    double root = (double)sqrtf((float)a);
    if (root == 0.0) return 0.0; /* sub-femtometre float underflow */
    root = 0.5 * (root + a / root);
    root = 0.5 * (root + a / root);
    /* asin(root) through root^5; cutoff bounds root < 0.000643.
     * The next term contributes < 3e-17 metres in exact arithmetic. */
    return 2.0 * EARTH_R_M * root * (1.0 + a * (1.0 / 6.0 + a * (3.0 / 40.0)));
}
