#!/exlibris/aleph/a23_1/product/bin/perl
#Script for online registration for internal users that have blocked patron account by global blocks
#Called by modified opac template bor-info-single-adm. 
# If OK, it deletes global block for non-registration patrons, writes circulation log (z309 table), proprietary text log and returns response to browser
#
#IN arguments (all required, POST method:
#	- borid (patron id, got from opac placeholder)
#	- password (retyped by patron on webpage)
#	- submit ('Y')
#
#OUT responses (text/plain)
#   'OK' - sucessfuly newly registrated
#   'OK noCard' - sucessfuly newly registrated, but user has no valid Card
#   'authenticationFailure' - authentication using patron IDs from API and password given by the user (www form) failed.
#   'alreadyRegistrated '+DD/MM/YYYY  - the patron has been already registrated and expiry date
#   'finishedStudyorJob' - the patron has global block that claims he has finished his study or employment/job, registration cannot be passed
#   'error '+text of the error message.
#   'plifModificationAll' - the whole patron record is protected by {z303}-plif-modification settings. It cannot be updated by api or procedure.
#
#by Matyas Bajger, library.osu.eu, May 2021, GNU GPL License
#

use strict;
use warnings;
use utf8;
binmode(STDOUT, ":utf8");
binmode(STDIN, ":utf8");
use URI::Escape;
use LWP;
use XML::Simple;
use CGI;
use POSIX qw/strftime/;
use DBI;
use Data::Dumper;

#initial variables
my $adm_base="osu50"; #lower case
my $xserver_url="https://katalog.osu.cz/X";
my $xborinfo_user="X-BOR-INFO"; #aleph user with privilegies to both bor-info and bor-auth x-services and Patron Record - Display
my $xborinfo_user_pas="SteSpaq8"; #password to this
my $xborupd_user="X-BOR-INFO"; #aleph user with privilegies to bor-update x-service and Patron Record - Update
my $xborupd_user_pas="SteSpaq8"; #password to this
my @block_not_registrated=(50); #array with values of global block for not registrated patrons
my @block_finished=(51,52); #array with values of global block for patrons with finished study or employment. Theese cannot be registrated.
my $libraryCardIDtype='01'; #type of Aleph ID used for library (student, staff) cards, for checking if user has a valid card
my $defaultAlephCardPrefix='BC-'; #For user without card. As Aleph sets own value for mandatory field ID, idetifiy it here
                                 #  by value set in util h 2, last-bor-id-1 
my $log='online_registration.log'; #for writing registrations, alerts and errors
my $sid = 'dbi:Oracle:host=localhost;sid=aleph23'; #Oracle System Identifier - SID. It is needed for updating the circulation log / z309 table
my $circ_log_event_no=92; #event no. to be written in circulation log (z309, Z309_ACTION)
my $circ_log_event_text="Online registrace"; #event text to be written in circ. log (z309)

my $admin_mail='matyas.bajger@osu.cz'; #for sending errors etc.
my $debug='1'; #debug mode, sends all registrations to admin_email, not just erros


#get request with comment from opac
my $comm_in = CGI->new;
my $comm_out = CGI->new;
if ( $comm_in->request_method() ne 'POST' ) { raiseError('WARNING','Input arguments send to cgi has not been sent as POSt method, but as '.$comm_in->request_method() ); }
my $borid = $comm_in->param('borid');
my $password = $comm_in->param('password');
my $consent = $comm_in->param('consent');
if (!defined $borid) { raiseError('ERROR','Patron ID is missing in URL arguments'); }
if (!defined $password) { raiseError('ERROR','Patron password is missing in URL arguments'); }
my $remote_host = $comm_in->remote_host();
my $remote_addr = $comm_in->remote_addr();
my $ip4log=( $remote_host ? $remote_host : $remote_addr );
our $now = strftime "%Y%m%d-%H:%M:%S", localtime;
our $now4circLog = strftime "%Y%m%d%H%M", localtime;
our $today = strftime "%Y%m%d", localtime;

print $comm_out->header(-type=>'text/plain', charset=>'utf-8');


#get patron logins from x-server api and authenticate
my $get_bor_url = $xserver_url.'?op=bor-info&library='.$adm_base.'&bor_id='.$borid.'&loans=N&cash=N&hold=N&format=1&user_name='.$xborinfo_user.'&user_password='.$xborinfo_user_pas;
my $xrequest = LWP::UserAgent->new;
my $borinfo = $xrequest->get( $get_bor_url );
unless ( $borinfo->is_success ) { raiseError('ERROR','Error in x-server bor-info response: '.$borinfo->status_line); }
my $xbor = XMLin( $borinfo->content, ForceArray=>1 ) || raiseError('ERROR','Error in x-server bor-info response. It cannot be parsed as XML'); 
if ( $xbor->{error} ) { raiseError('ERROR','X-server bor-info service claims error: '.$xbor->{error}[0]); }
my $passed_auth=0;
my $has_card=0;
for my $z308 ( @{$xbor->{'z308'}} ) {
   if ( $z308->{'z308-key-type'}[0] eq '02' and $z308->{'z308-status'}[0] ne 'NA' ) {
      my $login=$z308->{'z308-key-data'}[0];
      my $authenticate_url = $xserver_url.'?op=bor-auth&library='.$adm_base.'&bor_id='.$login.'&verification='.$password.'&user_name='.$xborinfo_user.'&user_password='.$xborinfo_user_pas;
      my $xrequest_auth = LWP::UserAgent->new;
      my $borauth = $xrequest->get( $authenticate_url );
      unless ( $borauth->is_success ) { raiseError('ERROR','Error in x-server bor-auth response: '.$borauth->status_line); }
      my $xborauth = XMLin( $borauth->content ) || raiseError('ERROR','Error in x-server bor-auth response. It cannot be parsed as XML'); 
      unless ( $xborauth->{error} ) {
         $passed_auth=1; last;
         }
      }
   #check for user card
   if ( $z308->{'z308-key-type'}[0] eq $libraryCardIDtype and ( $z308->{'z308-key-type'} ne '' or not ( $z308->{'z308-key-type'} =~ /^$defaultAlephCardPrefix/ ) ) ) {
      $has_card=1;
      }     
   }
if ( $passed_auth ) {
   #check if the patron has not been already registrated or finished his study/job
   my $delinq1 = $xbor->{'z303'}[0]->{'z303-delinq-1'}[0];
   my $delinq2 = $xbor->{'z303'}[0]->{'z303-delinq-2'}[0];
   my $delinq3 = $xbor->{'z303'}[0]->{'z303-delinq-3'}[0];
   #check for end of study/job 
   for my $x ( @block_finished ) {
      if ( $delinq1 eq $x or $delinq2 eq $x or $delinq3 eq $x ) { 
         open ( LOGFILE, ">>$log" );
         print LOGFILE "$now - $remote_host - $remote_addr : patron $borid wants to registrate, but he/she has blocks of finished study/employment\n";
         close(LOGFILE);
         raiseError('WARNING',"Patron $borid wants to registrate, but he/she has blocks of finished study/employment");
         print "finishedStudyorJob\n";
         exit 0;
         }
      }
   #check for really not registrated
   my $not_registrated=0;
   for my $x ( @block_not_registrated ) {
      if ( $delinq1 eq $x or $delinq2 eq $x or $delinq3 eq $x ) { $not_registrated=1; }
      }
   if ( !$not_registrated ) {
      my $expiry_date = $xbor->{'z305'}[0]->{'z305-expiry-date'}[0];
      raiseError('WARNING',"Patron $borid wants to registrate, but he/she has valid registration till $expiry_date\n");
      print "alreadyRegistrated $expiry_date\n";
      exit 0;
      }
   #check consent url argument
   if ( $consent ne 'Y' ) { raiseError('ERROR','Missing consent to registration sent by final user'); }
      
   #change global block to zero
   my %block_not_registrated_hash = map {$_ => 1} @block_not_registrated;
   for my $i ('1','2','3') {
      if ( exists $block_not_registrated_hash{ $xbor->{'z303'}[0]->{'z303-delinq-'.$i}[0] } ) {
         $xbor->{'z303'}[0]->{'z303-delinq-'.$i}[0]='00';
         $xbor->{'z303'}[0]->{'z303-delinq-n-'.$i}[0]='';
         $xbor->{'z303'}[0]->{'z303-delinq-'.$i.'-update-date'}[0]=$today;
         $xbor->{'z303'}[0]->{'z303-delinq-'.$i.'-cat-name'}[0]='online-reg';
         }
     
      }
   #check z303-plif-modification - if some updates are blocked, send alert to admin.
   #    If whole record is protected (value '1'), update/online reg. cannot be done
   #    20210714 checking of this value sometimes failes. Replaced by checking Rest PUT response below
  #   if ( index($xbor->{'z303'}[0]->{'z303-plif-modification'}[0],'1') > -1 ) { 
#       print "plifModificationAll\n";
#       mail2admin('Online registration - blocked by protected plif',"$now - patron with ID $borid wants to registrate from IP $ip4log, but this cannot be done as whole his record is protected by plif-modification settings.\n");
#       exit 0;
#       }
   
   #
   #write registration date and modify record for sending to api
   #  some values are translated by .../www_x_eng/global.trn or bor-info.trn rules. 
   #  For import (update) values cannot be in translated forms. These elements are deleted below
   $xbor->{'z305'}[0]->{'z305-registration-date'}[0] = $today;
   delete $xbor->{'check'};
   delete $xbor->{'session-id'};
   $xbor->{'z303'}[0]->{'match-id-type'}[0] = '00';
   $xbor->{'z303'}[0]->{'match-id'}[0] = $xbor->{'z303'}[0]->{'z303-id'}[0];
   $xbor->{'z303'}[0]->{'record-action'}[0] = 'U';
   delete $xbor->{'z303'}[0]->{'z303-home-library'};
   delete $xbor->{'z303'}[0]->{'z303-birth-date'};
   delete $xbor->{'z304'};
   $xbor->{'z305'}[0]->{'record-action'}[0] = 'U';
   delete $xbor->{'z305'}[0]->{'z305-bor-status'};
   delete $xbor->{'z305'}[0]->{'z305-expiry-date'};
   delete $xbor->{'z305'}[0]->{'z305-end-block-date'};
   delete $xbor->{'z308'};

   my $borupd_xml = '<p-file-20>'.XMLout($xbor, RootName => 'patron-record').'</p-file-20>';
   $borupd_xml =~ s/[\r\n]+$//g;
   #my $upd_bor_url = $xserver_url.'?op=update-bor&library='.$adm_base.'&update_flag=N&user_name='.$xborinfo_user.'&user_password='.$xborinfo_user_pas.'&xml_full_req='.urlencode($borupd_xml);
   my $xupdrequest = LWP::UserAgent->new;
   #my $borupd = $xupdrequest->post( $upd_bor_url, [ 'xml_full_req' => $borupd_xml ], );
   my $borupd = $xupdrequest->post( $xserver_url, [ 'op' => 'update_bor',  'library' => $adm_base,  'update_flag' => 'Y',  'user_name' => $xborupd_user,   user_password => $xborupd_user_pas,  'xml_full_req' => $borupd_xml ] );
   unless ( $borupd->is_success ) { raiseError('ERROR','Error in x-server update-bor response: '.$borupd->status_line); } 
   my $borupd_response = XMLin( $borupd->content, ForceArray=>1 ) || raiseError('ERROR','Error in x-server update-bor response. It cannot be parsed as XML');

   if ( grep(/Succeeded to REWRITE table z303/,@{$borupd_response->{'error'}}) 
             and 
        grep(/Succeeded to REWRITE table z305/,@{$borupd_response->{'error'}}) ) 
      {
         #20210714 check of plick modification supra replaced by checking the PUT Rest response
         if ( grep(/Succeeded to REWRITE table z303 with modification restrictions/,@{$borupd_response->{'error'}}) ) {
            print "plifModificationAll\n";
            mail2admin('Online registration - blocked by protected plif',"$now - patron with ID $borid wants to register from IP $ip4log, but this cannot be done as whole his record is protected by plif-modification settings.\n");
            open ( LOGFILE, ">>$log" );
            print LOGFILE "$now - online registration for patron $borid, IP $ip4log blocked by z303 protected plif: ".$xbor->{'z303'}[0]->{'z303-plif-modification'}[0]."\n";
            close(LOGFILE);
            exit 0;
            }

         #write circulation log z309
         circ_log_upd() or raiseError('ERROR','Error while updating z309 circulation log');
         #write text log
         open ( LOGFILE, ">>$log" );
         print LOGFILE "$now - online registration commited - borrowerID: $borid, IP address: $ip4log\n";
         close(LOGFILE);
         if ($debug) { mail2admin('New online registration (debug)',"$now - online registration commited - borrowerID: $borid, IP address: $ip4log\n"); }
         if ( $has_card ) {
            print "OK\n"; #all succeeded, registration passed - response to browser
            }
         else {
            print "OK noCard" ; #registration succeeded, but alerts that has no card
            }
      }
   else {
      my $bor_upd_error = join ' ',@{$borupd_response->{'error'}};   
      raiseError('ERROR','Error in x-server update-bor response: $bor_upd_error');
      }
   }
else {
   #write text log
   open ( LOGFILE, ">>$log" );
   print LOGFILE "$now - authentication failure - borrowerID: $borid, wrong password $password, IP address: $ip4log\n";
   close(LOGFILE);
   print "authenticationFailure\n"; #response to browser
   }


sub mail2admin {
   #arg1 subject,  arg2 mail text (body)
   my $subject=$_[0]; my $body=$_[1];
   open(MAIL, "|/usr/sbin/sendmail -t");
   print MAIL "To: ".$admin_mail."\n";
   print MAIL 'From: aleph@library.gen'."\n";
   print MAIL "Subject: $subject\n\n";
   print MAIL "$body\n";
   close(MAIL);
   }

sub raiseError {
   #arg1 WARNING || ERROR - en error the script dies
   #arg2 text of error/warn
   my $type=$_[0]; my $etext=$_[1];
   my $now=strftime "%Y%m%d-%H:%M:%S", localtime;
   open ( LOGFILE, ">>$log" );
   print LOGFILE "$now - $ip4log - $type $etext\n";
   close(LOGFILE);
   mail2admin( "Online registration (registration.cgi) $type", "$now $type $etext" );
   if ( $type eq 'ERROR' ) {
      print  "error $etext\n";
      exit 0;
      }
   } 


sub circ_log_upd {
   my $dbh = DBI->connect($sid, lc($adm_base), lc($adm_base) ) || raiseError('WARNING',"Error while connecting to database $sid for writing entry to the circulation log (z309) - ".DBI->errstr." This log has not been written");
   $dbh->{ AutoCommit } = 1;
   my $sth = $dbh->prepare("insert into z309 values( rpad('$borid',12)||to_char(sysdate,'YYYYMMDD')||lpad(to_char(LAST_RECORD_SEQUENCE.NEXTVAL),7,'0'), '000000000', '000000000000000', '000000000000000', 'online_reg', '$ip4log', '$now4circLog', $circ_log_event_no, 'N', '$circ_log_event_text', '$circ_log_event_text IP $ip4log','$now4circLog"."000', 0, null, 0)") || raiseError('WARNING','Error while prepaing sql insert to write the circulation log - '.DBI->errstr.'  This log has not been written');
   $sth->execute || raiseError('WARNING','Error while updating z309 circulation log - '.DBI->errstr.' This log has not been written');
   $dbh->disconnect();
   };

